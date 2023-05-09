from fastapi import FastAPI

app = FastAPI()


@app.get("/package")
def give_work():
    """Find an unscanned package and return it."""


@app.post("/package")
def update_verdict():
    """Update the database with the result of a package scan."""
