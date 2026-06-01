from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from api import switch, status, admin

app = FastAPI(title="Domain Switch Service", version="1.0.0")
app.include_router(switch.router)
app.include_router(status.router)
app.include_router(admin.router)


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    from config import SERVICE_PORT
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
