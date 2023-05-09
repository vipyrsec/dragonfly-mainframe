from fastapi import FastAPI

app = FastAPI()


@app.post("/queue-package")
def queue_package():
    """Add a package to the database to be scanned later."""


@app.get("/package")
def give_work():
    """Find an unscanned package and return it."""


@app.post("/package")
def update_verdict():
    """Update the database with the result of a package scan."""
