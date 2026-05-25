from pydantic import BaseModel
from fastapi import FastAPI, HTTPException

from src.model.predict_query import predict


app = FastAPI(
    title="SQL Query Classifier",
    description="API для классификации SQL-запросов на лёгкие и тяжёлые",
    version="1.0.0",
)


class QueryRequest(BaseModel):
    sql: str


@app.get("/")
def root():
    return {
        "message": "SQL Query Classifier API is running"
    }

@app.get("/health")
def health():
    return {
        "status": "ok"
    }

@app.post("/predict-complexity")
def predict_complexity(request: QueryRequest):
    try:
        result = predict(request.sql)

        return {
            "class": result["class"],
            "probability_heavy": round(result["probability_heavy"], 4),
            "top_contributions": result["top_contributions"],
        }

    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        )
