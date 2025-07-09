from fastapi import FastAPI
import boto3
from pydantic import BaseModel
from typing import List
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

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


# Product model (id will be auto-generated)
class Product(BaseModel):
    image: str
    title: str
    price: float
    rating: float
    purchases: int

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
@app.post("/add-products")
def add_products(products: List[Product]):
    with product_table.batch_writer() as batch:
        for product in products:
            new_id = get_next_product_id()
            item = product.dict()
            item['id'] = new_id
            batch.put_item(Item=item)
    return {"message": "Products added successfully"}

# GET endpoint to fetch all products
@app.get("/get-products")
def get_products():
    response = product_table.scan()
    return response.get("Items", [])
