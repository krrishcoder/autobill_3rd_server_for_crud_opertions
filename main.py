from fastapi import FastAPI
import boto3
from pydantic import BaseModel
from typing import List
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from uuid import uuid4
from datetime import datetime
from typing import Optional, List



app = FastAPI()

load_dotenv()

# CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# DynamoDB setup
dynamodb = boto3.resource('dynamodb')  # or your region
product_table = dynamodb.Table('Products')
counter_table = dynamodb.Table('ProductCounter')  # to store last used ID
plan_table = dynamodb.Table('PlanConfigurations')  # to store subscription plans



# Product model (id will be auto-generated)
class Product(BaseModel):
    image: str
    title: str
    price: float
    rating: float
    purchases: int


# Pydantic models
class PlanFeatures(BaseModel):
    max_detections_per_day: int
    analytics_enabled: bool
    basic_analytics: Optional[bool] = False
    advanced_analytics: Optional[bool] = False
    realtime_analytics: Optional[bool] = False
    email_support: bool
    mobile_camera_integration: bool
    basic_invoice_generation: bool
    api_access: bool
    priority_support: bool
    multi_camera_support: bool
    custom_training: bool
    advanced_reporting: Optional[bool] = False
    dedicated_support_manager: Optional[bool] = False
    custom_ai_model_training: Optional[bool] = False
    white_label_solution: Optional[bool] = False
    advanced_integrations: Optional[bool] = False
    custom_hardware_setup: Optional[bool] = False
    onsite_training: Optional[bool] = False

class SubscriptionPlan(BaseModel):
    plan_id: str
    name: str
    price: str
    currency: str
    duration_months: int
    features: PlanFeatures
    color: str
    popular: bool
    is_active: bool
    created_at: str
    updated_at: str

# GET next ID using atomic update
def get_next_product_id():
    response = counter_table.update_item(
        Key={"counter_name": "product_id"},
        UpdateExpression="SET last_id = last_id + :inc",
        ExpressionAttributeValues={":inc": 1},
        ReturnValues="UPDATED_NEW"
    )
    return int(response['Attributes']['last_id'])

# POST endpoint to add products
from decimal import Decimal

@app.post("/add-products")
def add_products(products: List[Product]):
    with product_table.batch_writer() as batch:
        for product in products:
            new_id = get_next_product_id()
            item = product.dict()

            # Convert float values to Decimal
            for key in ['price', 'rating']:
                item[key] = Decimal(str(item[key]))

            item['id'] = new_id
            batch.put_item(Item=item)
    return {"message": "Products added successfully"}



# GET endpoint to fetch all products
@app.get("/get-products")
def get_products():
    response = product_table.scan()
    return response.get("Items", [])


@app.get("/plans", response_model=List[SubscriptionPlan])
def get_subscription_plans():
    response = plan_table.scan()
    plans = response.get("Items", [])

    # Convert nested dicts as per the PlanFeatures model
    for plan in plans:
        if isinstance(plan.get("features"), dict):
            plan["features"] = PlanFeatures(**plan["features"])
    return plans
