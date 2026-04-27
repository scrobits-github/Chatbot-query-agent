from typing import Literal, TypedDict
from typing_extensions import NotRequired

class ResponseSchema(TypedDict):
    user_query: str
    query_response: str
    evaluation_state: Literal["True", "False"]
    retry_count: int
    instruction: str
    # Optional runtime metadata: rag | infiiot | greeting (greeting = skip retriever, go to evaluator).
    route: NotRequired[Literal["rag", "infiiot", "greeting"]]
    session_id: NotRequired[str]
    auth_token: NotRequired[str]