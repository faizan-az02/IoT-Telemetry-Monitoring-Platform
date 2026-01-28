import os
import json
import psutil
import time
from datetime import datetime
from pymongo import MongoClient

# Setting up MongoDB connection

client = MongoClient("mongodb://localhost:27017/")
db = client.telemetry_db
collection = db.telemetry_data

# Getting Device Information

dataset_size = int(input("Enter the dataset size you want to get: "))
time_interval = int(input("Enter the time interval between the samples: "))

device_id = os.getenv('DEVICE_ID', 'edge-1')

print(f"Device ID: {device_id}")


for i in range(dataset_size):
    now = datetime.now()

    # Collecting Telemetry Data
    telemetry_data = {
        "device_id": device_id,
        "cpu_usage (%)": psutil.cpu_percent(interval=1),
        "memory_usage (%)": psutil.virtual_memory().percent,
        "disk_usage (%)": psutil.disk_usage('/').percent,
        "timestamp": now,
        "datetime_str": now.strftime("%Y-%m-%d %H:%M:%S")
    }


    # Writing Telemetry Data to DB
    collection.insert_one(telemetry_data)
    print(f"Sample {i+1}/{dataset_size} collected.", end='\r')
    time.sleep(time_interval)

    time.sleep(time_interval)

    print(f"Sample {i+1}/{dataset_size} collected.", end = '\r')

print("\nTelemetry data collection complete.")
              

    