from abc import ABC, abstractmethod


class Output(ABC):
    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def status(self) -> list: ...
