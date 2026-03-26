from fastapi import FastAPI
from mangum import Mangum

app = FastAPI(title="Kognit AI HSE LLM API", root_path="/llm")


@app.get("/")
def read_root():
    return {"Hello": "World"}


@app.get("/items/{item_id}")
def read_item(item_id: int, q: str | None = None):
    return {"item_id": item_id, "q": q}


handler = Mangum(app, api_gateway_base_path="/llm")
