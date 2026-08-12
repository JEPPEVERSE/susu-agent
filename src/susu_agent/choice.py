from dataclasses import dataclass
from enum import Enum


class ChoiceAction(Enum):
    ASK = "ask"
    NEW_CHAT = "new_chat"
    EXIT = "exit"
    HISTORY = "history"
    STATUS = "status"


@dataclass(frozen=True, slots=True)
class Choice:
    action: ChoiceAction
    text: str | None = None

    def __post_init__(self) -> None:
        if self.action is ChoiceAction.ASK and not self.text:
            raise ValueError("A math question cannot be empty.")

        if self.action is not ChoiceAction.ASK and self.text is not None:
            raise ValueError("A command choice cannot contain question text.")

    @classmethod
    def from_raw(cls, raw_value: str) -> "Choice":
        value = raw_value.strip()

        if not value:
            raise ValueError("Please enter a math question or a command.")

        command = value.casefold()
        if command == "/new":
            return cls(action=ChoiceAction.NEW_CHAT)
        if command == "/exit":
            return cls(action=ChoiceAction.EXIT)
        if command == "/history":
            return cls(action=ChoiceAction.HISTORY)
        if command == "/status":
            return cls(action=ChoiceAction.STATUS)

        return cls(action=ChoiceAction.ASK, text=value)

    @property
    def question(self) -> str:
        if self.action is not ChoiceAction.ASK or self.text is None:
            raise ValueError("Only an ask choice contains a math question.")

        return self.text
