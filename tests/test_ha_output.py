import threading
import time
from dataclasses import replace

from conftest import FakeEngine
from test_wled_progress import race_state

from track_glow.engine import EngineState
from track_glow.ha import HaError
from track_glow.models import FeedStatus, Flag
from track_glow.outputs.ha import HaStatus, HomeAssistantOutput

SCENES = {
    "green": "scene.green",
    "red": "scene.red",
    "no_race": "scene.idle",
    "offline": "scene.offline",
    "blackout": "scene.blackout",
}


class FakeClient:
    def __init__(self, url, token, verify_tls=True):
        self.args = (url, token, verify_tls)
        self.calls = []
        self.fail = None
        self.block = None
        self.closed = False
        FakeClient.made.append(self)

    def turn_on_scene(self, entity):
        if self.block is not None:
            self.block.wait(5)
        self.calls.append(entity)
        if self.fail:
            raise HaError(self.fail)

    def close(self):
        self.closed = True


FakeClient.made = []


def make(engine=None, scenes=SCENES, hold=False, configure=True):
    FakeClient.made = []
    out = HomeAssistantOutput(engine or FakeEngine(race_state()), client_factory=FakeClient)
    if configure:
        out.configure(
            url="http://ha:8123", token="t", verify_tls=True, scenes=scenes, offline_hold=hold
        )
    return out


def calls():
    return [c for client in FakeClient.made for c in client.calls]


def test_off_until_configured():
    out = make(configure=False)
    out.step(0.0)
    assert out.ha_status() == HaStatus("off")
    assert FakeClient.made == []


def test_sends_mapped_scene_once():
    out = make()
    out.step(0.0)
    out.step(0.25)
    assert calls() == ["scene.green"]
    assert out.ha_status() == HaStatus("ok", "", "scene.green")
    assert FakeClient.made[0].args == ("http://ha:8123", "t", True)


def test_key_change_sends_again():
    engine = FakeEngine(race_state())
    out = make(engine)
    out.step(0.0)
    engine.state = race_state(Flag.RED)
    out.step(0.25)
    assert calls() == ["scene.green", "scene.red"]


def test_unmapped_key_is_idle_not_error():
    out = make(FakeEngine(race_state(Flag.YELLOW)))
    out.step(0.0)
    assert calls() == []
    assert out.ha_status() == HaStatus("idle", "No scene for yellow")


def test_failure_retries_after_interval_then_recovers():
    out = make()
    out.step(0.0)
    client = FakeClient.made[0]
    client.fail = "Home Assistant returned HTTP 500"
    out._sent_key = None
    out.step(1.0)
    assert out.ha_status() == HaStatus("error", "Home Assistant returned HTTP 500")
    out.step(5.9)
    assert len(client.calls) == 2
    client.fail = None
    out.step(6.1)
    assert len(client.calls) == 3
    assert out.ha_status().state == "ok"


def test_key_change_during_retry_sends_new_key():
    engine = FakeEngine(race_state())
    out = make(engine)
    out.step(0.0)
    FakeClient.made[0].fail = "down"
    engine.state = race_state(Flag.RED)
    out.step(0.25)
    FakeClient.made[0].fail = None
    engine.state = race_state(Flag.GREEN)
    out.step(0.5)
    assert calls() == ["scene.green", "scene.red", "scene.green"]


def test_paused_sends_nothing_and_keeps_status():
    engine = FakeEngine(race_state())
    out = make(engine)
    out.step(0.0)
    engine.state = replace(race_state(Flag.RED), mode="paused")
    out.step(0.25)
    assert calls() == ["scene.green"]
    assert out.ha_status().scene == "scene.green"


def test_blackout_scene():
    out = make(FakeEngine(replace(race_state(), mode="blackout")))
    out.step(0.0)
    assert calls() == ["scene.blackout"]


def test_no_race_scene():
    out = make(FakeEngine(EngineState(feed=FeedStatus("ok"))))
    out.step(0.0)
    assert calls() == ["scene.idle"]


def test_offline_scene_and_hold():
    engine = FakeEngine(race_state())
    out = make(engine)
    out.step(0.0)
    engine.state = EngineState(feed=FeedStatus("offline"))
    out.step(0.25)
    assert calls() == ["scene.green", "scene.offline"]

    engine = FakeEngine(race_state())
    out = make(engine, hold=True)
    out.step(0.0)
    engine.state = EngineState(feed=FeedStatus("offline"))
    out.step(0.25)
    assert calls() == ["scene.green"]


def test_override_wins_over_offline():
    out = make(FakeEngine(EngineState(feed=FeedStatus("offline"), override=Flag.RED)))
    out.step(0.0)
    assert calls() == ["scene.red"]


def test_configure_resends_with_new_client_and_closes_old():
    out = make()
    out.step(0.0)
    out.configure(url="http://ha2", token="u", verify_tls=False, scenes=SCENES, offline_hold=False)
    out.step(0.25)
    assert [c.args for c in FakeClient.made] == [
        ("http://ha:8123", "t", True),
        ("http://ha2", "u", False),
    ]
    assert FakeClient.made[0].closed
    assert FakeClient.made[1].calls == ["scene.green"]


def test_configure_empty_url_turns_off():
    out = make()
    out.step(0.0)
    out.configure(url="", token="", verify_tls=True, scenes={}, offline_hold=False)
    out.step(0.25)
    assert out.ha_status() == HaStatus("off")
    assert FakeClient.made[0].closed


def test_stale_in_flight_result_dropped():
    out = make()
    out.step(0.0)
    FakeClient.made[0].block = threading.Event()
    FakeClient.made[0].fail = "old failure"
    out._sent_key = None
    t = threading.Thread(target=out.step, args=(1.0,))
    t.start()
    time.sleep(0.05)
    out.configure(url="http://ha2", token="u", verify_tls=True, scenes=SCENES, offline_hold=False)
    FakeClient.made[0].block.set()
    t.join(5)
    assert out.ha_status().state != "error"
    out.step(1.25)
    assert out.ha_status() == HaStatus("ok", "", "scene.green")


def test_stop_is_prompt_with_blocked_call():
    FakeClient.made = []
    gate = threading.Event()

    class Blocking(FakeClient):
        def turn_on_scene(self, entity):
            gate.wait(5)

    out = HomeAssistantOutput(FakeEngine(race_state()), client_factory=Blocking, tick=0.01)
    out.configure(url="http://ha", token="t", verify_tls=True, scenes=SCENES, offline_hold=False)
    out.start()
    time.sleep(0.1)
    t0 = time.monotonic()
    out.stop()
    assert time.monotonic() - t0 < 1.5
    gate.set()


def test_retry_waits_after_slow_failure():
    clock = {"t": 0.0}

    class Slow(FakeClient):
        def turn_on_scene(self, entity):
            self.calls.append(entity)
            clock["t"] += 5.0
            raise HaError("timeout")

    FakeClient.made = []
    out = HomeAssistantOutput(
        FakeEngine(race_state()), client_factory=Slow, clock=lambda: clock["t"]
    )
    out.configure(url="http://ha", token="t", verify_tls=True, scenes=SCENES, offline_hold=False)
    out.step(0.0)
    out.step(clock["t"])
    assert len(FakeClient.made[0].calls) == 1
    out.step(clock["t"] + 5.0)
    assert len(FakeClient.made[0].calls) == 2


def test_status_when_paused_or_waiting_for_flag():
    out = make(FakeEngine(replace(race_state(), mode="paused")))
    out.step(0.0)
    assert out.ha_status() == HaStatus("idle", "Paused")
    out = make(FakeEngine(EngineState(feed=FeedStatus("offline"))), hold=True)
    out.step(0.0)
    assert out.ha_status() == HaStatus("idle", "Waiting for a flag")


WITH_DEFAULT = {**SCENES, "checkered": "scene.checkered", "default": "scene.warm"}


def test_reverts_to_default_after_flash_hold():
    out = make(scenes=WITH_DEFAULT)
    out.step(0.0)
    out.step(1.4)
    assert calls() == ["scene.green"]
    out.step(1.5)
    out.step(3.0)
    assert calls() == ["scene.green", "scene.warm"]
    assert out.ha_status() == HaStatus("ok", "", "scene.warm")


def test_checkered_holds_five_seconds_before_default():
    out = make(FakeEngine(race_state(Flag.CHECKERED)), scenes=WITH_DEFAULT)
    out.step(0.0)
    out.step(4.9)
    assert calls() == ["scene.checkered"]
    out.step(5.0)
    assert calls() == ["scene.checkered", "scene.warm"]


def test_new_flag_mid_hold_restarts_timer():
    engine = FakeEngine(race_state())
    out = make(engine, scenes=WITH_DEFAULT)
    out.step(0.0)
    engine.state = race_state(Flag.RED)
    out.step(1.0)
    out.step(2.4)
    assert calls() == ["scene.green", "scene.red"]
    out.step(2.5)
    assert calls() == ["scene.green", "scene.red", "scene.warm"]


def test_no_default_scene_never_reverts():
    out = make()
    out.step(0.0)
    out.step(10.0)
    assert calls() == ["scene.green"]


def test_steady_scenes_do_not_revert():
    out = make(FakeEngine(EngineState(feed=FeedStatus("ok"))), scenes=WITH_DEFAULT)
    out.step(0.0)
    out.step(10.0)
    assert calls() == ["scene.idle"]


def test_pause_reverts_to_default_and_resume_resends_flag():
    engine = FakeEngine(race_state())
    out = make(engine, scenes=WITH_DEFAULT)
    out.step(0.0)
    engine.state = replace(race_state(), mode="paused")
    out.step(0.5)
    out.step(0.75)
    assert calls() == ["scene.green", "scene.warm"]
    engine.state = race_state()
    out.step(1.0)
    assert calls() == ["scene.green", "scene.warm", "scene.green"]
    out.step(2.5)
    assert calls() == ["scene.green", "scene.warm", "scene.green", "scene.warm"]


def test_pause_after_hold_reverted_does_not_resend_default():
    engine = FakeEngine(race_state())
    out = make(engine, scenes=WITH_DEFAULT)
    out.step(0.0)
    out.step(1.5)
    engine.state = replace(race_state(), mode="paused")
    out.step(2.0)
    assert calls() == ["scene.green", "scene.warm"]
    engine.state = race_state()
    out.step(2.5)
    assert calls() == ["scene.green", "scene.warm", "scene.green"]


def test_paused_before_any_flag_leaves_lights_alone():
    out = make(FakeEngine(replace(race_state(), mode="paused")), scenes=WITH_DEFAULT)
    out.step(0.0)
    assert calls() == []


def test_failed_revert_retries_after_interval():
    out = make(scenes=WITH_DEFAULT)
    out.step(0.0)
    client = FakeClient.made[0]
    client.fail = "down"
    out.step(1.5)
    assert out.ha_status() == HaStatus("error", "down")
    out.step(3.0)
    assert calls() == ["scene.green", "scene.warm"]
    client.fail = None
    out.step(6.6)
    assert calls() == ["scene.green", "scene.warm", "scene.warm"]
    assert out.ha_status() == HaStatus("ok", "", "scene.warm")
    out.step(9.0)
    assert len(calls()) == 3


def test_config_repr_hides_token():
    out = make()
    assert "'t'" not in repr(out._config) and "token=" not in repr(out._config)
