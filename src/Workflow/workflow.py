from langgraph.graph import StateGraph, START, END
from langchain_google_genai import ChatGoogleGenerativeAI
from settings import GOOGLE_API_KEY 
from src.agents.evaluator_agent import evaluator_agent
from src.agents.retriver_agent import retriver_agent
from src.schemas.response_schema import ResponseSchema

model = ChatGoogleGenerativeAI(model="gemini-2.0-flash",google_api_key = GOOGLE_API_KEY)

def evaluation_edge(state: ResponseSchema):
    return "retriver_agent" if state["evaluation_state"] == "False" else END

graph = StateGraph(ResponseSchema)

graph.add_node('retriver_agent', retriver_agent)
graph.add_node('evaluator_agent', evaluator_agent)

graph.add_edge(START, 'retriver_agent')
graph.add_edge('retriver_agent', 'evaluator_agent')
graph.add_conditional_edges(
    "evaluator_agent",
    evaluation_edge,
    {
        "retriver_agent": "retriver_agent",
        END: END
    }
)

workflow = graph.compile()

if __name__ == "__main__":
    initial_state = {
        "user_query": "What did the anonymous BCGEU member post on social media about the government's raise offer during the strike?",
        "query_response": "",
        "evaluation_state": "",
        "retry_count": 0,
        "instruction": ""
    }

    final_state = workflow.invoke(initial_state, config={"verbose": True})

    print(final_state)
