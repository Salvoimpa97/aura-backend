from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
import motor.motor_asyncio

# Vercel cerca esattamente questa riga
app = FastAPI()

# --- CONFIGURAZIONE DATABASE ---
MONGO_URI = mongodb+srv://salvoimpa88_db_user:Z3pavGvthxDaVwky@cluster0.lz6k120.mongodb.net/?appName=Cluster0 

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = client.aurafitness

# --- MODELLI DATI ---
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

# --- ROTTE API ---
@app.get("/api/health")
async def health_check():
    return {"status": "ok", "message": "Aura Fitness Backend Vercel Attivo!"}

@app.post("/api/workouts")
async def create_workout(workout: Workout):
    new_workout = await db.workouts.insert_one(workout.dict())
    return {"status": "success", "id": str(new_workout.inserted_id)}

@app.get("/api/workouts/{device_id}")
async def get_workouts(device_id: str):
    workouts = await db.workouts.find({"device_id": device_id}).to_list(100)
    for w in workouts:
        w["_id"] = str(w["_id"])
    return workouts
