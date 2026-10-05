from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
import motor.motor_asyncio
import os
import certifi

app = FastAPI()

MONGO_URI = os.getenv("MONGO_URI")

# Usiamo certifi per forzare la verifica SSL su Vercel
if MONGO_URI:
    ca = certifi.where()
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI, tlsCAFile=ca)
    db = client.aurafitness
else:
    db = None

class Exercise(BaseModel):
    name: str
    muscle_group: str
    sets: int
    reps: str
    weight: Optional[float] = None
    rest: str
    notes: Optional[str] = None

class Workout(BaseModel):
    device_id: str
    name: str
    focus: str
    source: str = "manual"
    exercises: List[Exercise]
    created_at: datetime = Field(default_factory=datetime.utcnow)

@app.get("/api/health")
async def health_check():
    if db is None:
        return {"status": "warning", "message": "Backend Vercel attivo, in attesa di MongoDB..."}
    return {"status": "ok", "message": "Aura Fitness Backend Vercel Attivo e DB Connesso con Sicurezza SSL!"}

@app.post("/api/workouts")
async def create_workout(workout: Workout):
    if db is None:
        return {"status": "error", "message": "Database non connesso"}
    new_workout = await db.workouts.insert_one(workout.model_dump())
    return {"status": "success", "id": str(new_workout.inserted_id)}

@app.get("/api/workouts/{device_id}")
async def get_workouts(device_id: str):
    if db is None:
        return []
    workouts = await db.workouts.find({"device_id": device_id}).to_list(100)
    for w in workouts:
        w["_id"] = str(w["_id"])
    return workouts
