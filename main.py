


from fastapi import FastAPI
import boto3
from pydantic import BaseModel
from typing import List
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from uuid import uuid4
from datetime import datetime
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Depends, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, Any, List
import boto3
from botocore.exceptions import ClientError
import hashlib
import json
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import uuid
import logging
import time
from decimal import Decimal

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

# Table references
users_table = dynamodb.Table('autobill-users')
subscriptions_table = dynamodb.Table('autobill-user-subscriptions')
expiration_table = dynamodb.Table('autobill-subscription-expiration')

# DynamoDB table for user products
user_products_table = dynamodb.Table('UserProducts')
# DynamoDB table for user bills
user_bills_table = dynamodb.Table('UserBills')

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

class PlanDetails(BaseModel):
    plan_id: str
    price: str
    duration_months: int

class Plan(BaseModel):
    plan_id: str
    name: str
    price: str
    currency: str = "INR"
    duration_months: int
    features: PlanFeatures
    color: str
    popular: bool = False
    is_active: bool = True
    description: Optional[str] = None

class UsageStats(BaseModel):
    detections_used_today: int = 0
    detections_used_this_month: int = 0
    last_detection_date: Optional[str] = None

class UserRegistration(BaseModel):
    user_id: str
    shop_id: str
    name: str
    shop_name: str
    email: EmailStr
    password: str
    telegram_user_id: str
    phone: Optional[str] = None
    selected_plan: str
    plan_details: Optional[PlanDetails] = None

class RegistrationResponse(BaseModel):
    success: bool
    message: str
    user_id: str
    shop_id: str
    subscription_id: Optional[str] = None

class UserProduct(BaseModel):
    user_id: str
    product_id: int
    title: str
    image: str
    price: float
    rating: float
    purchases: int
    # Add more fields if you want to allow more customization

class BillItem(BaseModel):
    product_id: int
    title: str
    quantity: int
    price: float
    total: float

class Bill(BaseModel):
    bill_id: str
    user_id: str
    shop_name: str
    items: List[BillItem]
    total_amount: float
    created_at: str
    # Add more fields as needed (e.g., payment_method, customer_name, etc.)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class LoginResponse(BaseModel):
    success: bool
    message: str
    user_id: str = None
    name: str = None
    email: EmailStr = None
    shop_name: str = None
    telegram_user_id: str = None
    phone: str = None
    # Add more fields as needed

# Helper functions
def safe_int(value) -> int:
    """Convert various types to int, handling Decimal objects"""
    if isinstance(value, Decimal):
        return int(value)
    if isinstance(value, str):
        return int(value)
    return int(value)

def safe_str(value) -> str:
    """Convert various types to str, handling Decimal objects"""
    if isinstance(value, Decimal):
        return str(value)
    return str(value)

def hash_password(password: str) -> str:
    """Hash password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def generate_subscription_id() -> str:
    """Generate unique subscription ID"""
    return f"sub_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}"

def calculate_expiration_date(start_date: datetime, duration_months: int) -> datetime:
    """Calculate subscription expiration date"""
    # Add months to start date
    year = start_date.year
    month = start_date.month + duration_months
    
    # Handle year overflow
    while month > 12:
        year += 1
        month -= 12
    
    return datetime(year, month, start_date.day, start_date.hour, start_date.minute, start_date.second)

def datetime_to_timestamp(dt: datetime) -> int:
    """Convert datetime to Unix timestamp"""
    return int(dt.timestamp())

def convert_dynamodb_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Convert DynamoDB item with Decimal values to regular Python types"""
    if isinstance(item, dict):
        return {k: convert_dynamodb_item(v) for k, v in item.items()}
    elif isinstance(item, list):
        return [convert_dynamodb_item(v) for v in item]
    elif isinstance(item, Decimal):
        # Convert Decimal to int if it's a whole number, otherwise to float
        if item % 1 == 0:
            return int(item)
        else:
            return float(item)
    else:
        return item

# GET next ID using atomic update
def get_next_product_id():
    response = counter_table.update_item(
        Key={"counter_name": "product_id"},
        UpdateExpression="SET last_id = last_id + :inc",
        ExpressionAttributeValues={":inc": 1},
        ReturnValues="UPDATED_NEW"
    )
    return int(response['Attributes']['last_id'])

async def check_user_exists(email: str) -> bool:
    """Check if user already exists"""
    try:
        response = users_table.scan(
            FilterExpression='email = :email',
            ExpressionAttributeValues={':email': email}
        )
        return len(response['Items']) > 0
    except ClientError as e:
        logger.error(f"Error checking user existence: {e}")
        return False

async def create_user_record(user_data: UserRegistration) -> Dict[str, Any]:
    """Create user record in DynamoDB"""
    now = datetime.now()
    
    user_item = {
        'user_id': user_data.user_id,
        'name': user_data.name,
        'email': user_data.email,
        'shop_name': user_data.shop_name,
        'password_hash': hash_password(user_data.password),
        'telegram_user_id': user_data.telegram_user_id,
        'phone': user_data.phone or "",
        'created_at': now.isoformat(),
        'updated_at': now.isoformat(),
        'status': 'active',
        'email_verified': False
    }
    
    try:
        users_table.put_item(Item=user_item)
        logger.info(f"User created successfully: {user_data.user_id}")
        return user_item
    except ClientError as e:
        logger.error(f"Error creating user: {e}")
        raise HTTPException(status_code=500, detail="Failed to create user")

async def create_subscription_record(user_data: UserRegistration, plan_data: Dict[str, Any]) -> str:
    """Create subscription record in DynamoDB"""
    now = datetime.now()
    subscription_id = generate_subscription_id()
    
    # Convert plan_data to handle Decimal objects
    plan_data = convert_dynamodb_item(plan_data)
    
    # Calculate expiration date - ensure duration_months is an integer
    duration_months = safe_int(plan_data.get('duration_months', 1))
    expiration_date = calculate_expiration_date(now, duration_months)
    expiration_timestamp = datetime_to_timestamp(expiration_date)
    
    # Create features snapshot from plan
    features_snapshot = {
        key: value for key, value in plan_data.get('features', {}).items()
        if key in ['max_detections_per_day', 'analytics_enabled', 'advanced_analytics', 'api_access', 'priority_support']
    }
    
    # Initialize usage stats
    usage_stats = {
        'detections_used_today': 0,
        'detections_used_this_month': 0,
        'last_detection_date': None
    }
    
    subscription_item = {
        'user_id': user_data.user_id,
        'subscription_id': subscription_id,
        'plan_id': user_data.selected_plan,
        'status': 'pending',  # Will be updated to 'active' after payment
        'purchase_date': now.isoformat(),
        'start_date': now.isoformat(),
        'end_date': expiration_date.isoformat(),
        'expiration_timestamp': expiration_timestamp,
        'auto_renew': True,
        'payment_method': '',  # Will be updated after payment
        'payment_id': '',      # Will be updated after payment
        'amount_paid': safe_str(plan_data.get('price', '0')),
        'currency': plan_data.get('currency', 'INR'),
        'duration_months': duration_months,
        'features_snapshot': features_snapshot,
        'usage_stats': usage_stats,
        'renewal_reminder_sent': False,
        'expiration_warning_sent': False,
        'created_at': now.isoformat(),
        'updated_at': now.isoformat()
    }
    
    try:
        subscriptions_table.put_item(Item=subscription_item)
        logger.info(f"Subscription created successfully: {subscription_id}")
        
        # Create expiration record for tracking
        expiration_item = {
            'expiration_date': expiration_date.strftime('%Y-%m-%d'),
            'user_id': user_data.user_id,
            'subscription_id': subscription_id,
            'plan_id': user_data.selected_plan,
            'expiration_timestamp': expiration_timestamp,
            'status': 'active',
            'email': user_data.email,
            'telegram_user_id': user_data.telegram_user_id,
            'shop_name': user_data.shop_name,
            'amount_paid': safe_str(plan_data.get('price', '0')),
            'auto_renew': True,
            'ttl': expiration_timestamp + 2592000  # TTL 30 days after expiration
        }
        expiration_table.put_item(Item=expiration_item)
        
        return subscription_id
    except ClientError as e:
        logger.error(f"Error creating subscription: {e}")
        raise HTTPException(status_code=500, detail="Failed to create subscription")

async def get_plan_by_id(plan_id: str) -> Optional[Dict[str, Any]]:
    """Get plan details by ID"""
    try:
        response = plan_table.get_item(Key={'plan_id': plan_id})
        item = response.get('Item')
        if item:
            return convert_dynamodb_item(item)
        return None
    except ClientError as e:
        logger.error(f"Error fetching plan: {e}")
        return None

# API Routes
@app.get("/")
async def root():
    """Health check endpoint"""
    return {"message": "AutoBill Registration API is running", "version": "1.0.0"}

@app.get("/plans", response_model=List[Plan])
async def get_plans():
    """Get all available subscription plans"""
    try:
        response = plan_table.scan(
            FilterExpression='is_active = :active',
            ExpressionAttributeValues={':active': True}
        )
        plans = response['Items']
        
        # Convert Decimal objects to regular Python types
        plans = [convert_dynamodb_item(plan) for plan in plans]
        
        # If no plans in database, return default plans
        if not plans:
            default_plans = [
                {
                    'plan_id': 'starter',
                    'name': 'Starter',
                    'price': '999',
                    'currency': 'INR',
                    'duration_months': 1,
                    'features': {
                        'max_detections_per_day': 100,
                        'analytics_enabled': True,
                        'basic_analytics': True,
                        'advanced_analytics': False,
                        'realtime_analytics': False,
                        'email_support': True,
                        'priority_support': False,
                        'dedicated_support_manager': False,
                        'mobile_camera_integration': True,
                        'multi_camera_support': False,
                        'basic_invoice_generation': True,
                        'advanced_reporting': False,
                        'api_access': False,
                        'custom_training': False,
                        'custom_ai_model_training': False,
                        'white_label_solution': False,
                        'advanced_integrations': False,
                        'custom_hardware_setup': False,
                        'onsite_training': False
                    },
                    'color': 'from-blue-500 to-blue-600',
                    'popular': False,
                    'is_active': True,
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                },
                {
                    'plan_id': 'professional',
                    'name': 'Professional',
                    'price': '2499',
                    'currency': 'INR',
                    'duration_months': 3,
                    'features': {
                        'max_detections_per_day': 500,
                        'analytics_enabled': True,
                        'basic_analytics': False,
                        'advanced_analytics': True,
                        'realtime_analytics': False,
                        'email_support': True,
                        'priority_support': True,
                        'dedicated_support_manager': False,
                        'mobile_camera_integration': True,
                        'multi_camera_support': True,
                        'basic_invoice_generation': True,
                        'advanced_reporting': True,
                        'api_access': True,
                        'custom_training': True,
                        'custom_ai_model_training': False,
                        'white_label_solution': False,
                        'advanced_integrations': False,
                        'custom_hardware_setup': False,
                        'onsite_training': False
                    },
                    'color': 'from-purple-500 to-purple-600',
                    'popular': True,
                    'is_active': True,
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                },
                {
                    'plan_id': 'enterprise',
                    'name': 'Enterprise',
                    'price': '4999',
                    'currency': 'INR',
                    'duration_months': 6,
                    'features': {
                        'max_detections_per_day': -1,  # Unlimited
                        'analytics_enabled': True,
                        'basic_analytics': False,
                        'advanced_analytics': True,
                        'realtime_analytics': True,
                        'email_support': True,
                        'priority_support': True,
                        'dedicated_support_manager': True,
                        'mobile_camera_integration': True,
                        'multi_camera_support': True,
                        'basic_invoice_generation': True,
                        'advanced_reporting': True,
                        'api_access': True,
                        'custom_training': True,
                        'custom_ai_model_training': True,
                        'white_label_solution': True,
                        'advanced_integrations': True,
                        'custom_hardware_setup': True,
                        'onsite_training': True
                    },
                    'color': 'from-amber-500 to-orange-500',
                    'popular': False,
                    'is_active': True,
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                }
            ]
            return default_plans
        
        return plans
    except ClientError as e:
        logger.error(f"Error fetching plans: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch plans")

@app.get("/subscription-plans", response_model=List[SubscriptionPlan])
def get_subscription_plans():
    """Get subscription plans from PlanConfigurations table"""
    response = plan_table.scan()
    plans = response.get("Items", [])

    # Convert Decimal objects and nested dicts as per the PlanFeatures model
    for plan in plans:
        plan = convert_dynamodb_item(plan)
        if isinstance(plan.get("features"), dict):
            plan["features"] = PlanFeatures(**plan["features"])
    return plans

@app.post("/register", response_model=RegistrationResponse)
async def register_user(user_data: UserRegistration):
    """Register a new user with subscription"""
    try:
        # Check if user already exists
        if await check_user_exists(user_data.email):
            raise HTTPException(
                status_code=400, 
                detail="User with this email already exists"
            )
        
        # Get plan details
        plan_data = await get_plan_by_id(user_data.selected_plan)
        if not plan_data:
            raise HTTPException(
                status_code=400, 
                detail="Invalid plan selected"
            )
        
        # Create user record
        user_record = await create_user_record(user_data)
        
        # Create subscription record
        subscription_id = await create_subscription_record(user_data, plan_data)
        
        logger.info(f"User registration completed: {user_data.user_id}")
        
        return RegistrationResponse(
            success=True,
            message="User registered successfully",
            user_id=user_data.user_id,
            shop_id=user_data.shop_id,
            subscription_id=subscription_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during registration: {e}")
        raise HTTPException(
            status_code=500, 
            detail="An unexpected error occurred during registration"
        )

@app.post("/login", response_model=LoginResponse)
async def login_user(login: LoginRequest):
    """
    Login endpoint: verifies email and password (hashed).
    """
    try:
        # Find user by email
        response = users_table.scan(
            FilterExpression='email = :email',
            ExpressionAttributeValues={':email': login.email}
        )
        if not response['Items']:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        user = response['Items'][0]
        # Check password hash
        if user['password_hash'] != hash_password(login.password):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        # Prepare response (exclude password_hash)
        user_info = convert_dynamodb_item(user)
        user_info.pop('password_hash', None)
        return LoginResponse(
            success=True,
            message="Login successful",
            user_id=user_info.get('user_id'),
            name=user_info.get('name'),
            email=user_info.get('email'),
            shop_name=user_info.get('shop_name'),
            telegram_user_id=user_info.get('telegram_user_id'),
            phone=user_info.get('phone', None)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during login: {e}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred during login")

@app.get("/user/{user_id}")
async def get_user(user_id: str):
    """Get user details by ID"""
    try:
        response = users_table.get_item(Key={'user_id': user_id})
        if 'Item' not in response:
            raise HTTPException(status_code=404, detail="User not found")
        
        user = convert_dynamodb_item(response['Item'])
        # Remove sensitive information
        user.pop('password_hash', None)
        
        return user
    except ClientError as e:
        logger.error(f"Error fetching user: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch user")

@app.get("/subscription/{user_id}")
async def get_user_subscription(user_id: str):
    """Get user's current subscription details"""
    try:
        response = subscriptions_table.query(
            KeyConditionExpression='user_id = :user_id',
            ExpressionAttributeValues={':user_id': user_id},
            ScanIndexForward=False,  # Sort by subscription_id descending
            Limit=1
        )
        
        if not response['Items']:
            raise HTTPException(status_code=404, detail="Subscription not found")
        
        return convert_dynamodb_item(response['Items'][0])
        
    except ClientError as e:
        logger.error(f"Error fetching subscription: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch subscription")

@app.put("/subscription/{user_id}/{subscription_id}/status")
async def update_subscription_status(user_id: str, subscription_id: str, status: str, payment_id: str = None, payment_method: str = None):
    """Update subscription status (for payment confirmation)"""
    try:
        update_expression = 'SET #status = :status, updated_at = :updated_at'
        expression_values = {
            ':status': status,
            ':updated_at': datetime.now().isoformat()
        }
        expression_names = {'#status': 'status'}
        
        # Add payment details if provided
        if payment_id:
            update_expression += ', payment_id = :payment_id'
            expression_values[':payment_id'] = payment_id
            
        if payment_method:
            update_expression += ', payment_method = :payment_method'
            expression_values[':payment_method'] = payment_method
        
        # Update subscription status
        subscriptions_table.update_item(
            Key={'user_id': user_id, 'subscription_id': subscription_id},
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expression_names,
            ExpressionAttributeValues=expression_values
        )
        
        # Update expiration table status if payment is confirmed
        if status == 'active':
            # Get subscription details for expiration update
            sub_response = subscriptions_table.get_item(
                Key={'user_id': user_id, 'subscription_id': subscription_id}
            )
            
            if 'Item' in sub_response:
                subscription = convert_dynamodb_item(sub_response['Item'])
                exp_date = datetime.fromisoformat(subscription['end_date'].replace('Z', '+00:00'))
                
                expiration_table.update_item(
                    Key={
                        'expiration_date': exp_date.strftime('%Y-%m-%d'),
                        'user_id': user_id
                    },
                    UpdateExpression='SET #status = :status',
                    ExpressionAttributeNames={'#status': 'status'},
                    ExpressionAttributeValues={':status': 'active'}
                )
        
        return {"message": "Subscription status updated successfully"}
        
    except ClientError as e:
        logger.error(f"Error updating subscription status: {e}")
        raise HTTPException(status_code=500, detail="Failed to update subscription status")

@app.put("/subscription/{user_id}/{subscription_id}/usage")
async def update_usage_stats(user_id: str, subscription_id: str, detections_used: int):
    """Update usage statistics for a subscription"""
    try:
        now = datetime.now()
        
        # Get current subscription to check current usage
        sub_response = subscriptions_table.get_item(
            Key={'user_id': user_id, 'subscription_id': subscription_id}
        )
        
        if 'Item' not in sub_response:
            raise HTTPException(status_code=404, detail="Subscription not found")
        
        subscription = convert_dynamodb_item(sub_response['Item'])
        current_usage = subscription.get('usage_stats', {})
        
        # Update usage stats
        subscriptions_table.update_item(
            Key={'user_id': user_id, 'subscription_id': subscription_id},
            UpdateExpression='SET usage_stats.detections_used_today = :today, usage_stats.detections_used_this_month = :month, usage_stats.last_detection_date = :last_date, updated_at = :updated_at',
            ExpressionAttributeValues={
                ':today': detections_used,
                ':month': current_usage.get('detections_used_this_month', 0) + detections_used,
                ':last_date': now.isoformat(),
                ':updated_at': now.isoformat()
            }
        )
        
        return {"message": "Usage statistics updated successfully"}
        
    except ClientError as e:
        logger.error(f"Error updating usage stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to update usage statistics")

@app.get("/expiring-subscriptions/{date}")
async def get_expiring_subscriptions(date: str):
    """Get subscriptions expiring on a specific date (YYYY-MM-DD format)"""
    try:
        response = expiration_table.query(
            KeyConditionExpression='expiration_date = :date',
            ExpressionAttributeValues={':date': date}
        )
        
        return [convert_dynamodb_item(item) for item in response['Items']]
        
    except ClientError as e:
        logger.error(f"Error fetching expiring subscriptions: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch expiring subscriptions")

@app.post("/plans")
async def create_plan(plan: Plan):
    """Create a new subscription plan (Admin only)"""
    try:
        plan_item = {
            'plan_id': plan.plan_id,
            'name': plan.name,
            'price': plan.price,
            'currency': plan.currency,
            'duration_months': plan.duration_months,
            'features': plan.features.dict(),
            'color': plan.color,
            'popular': plan.popular,
            'is_active': plan.is_active,
            'description': plan.description,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        plan_table.put_item(Item=plan_item)
        return {"message": "Plan created successfully", "plan_id": plan.plan_id}
        
    except ClientError as e:
        logger.error(f"Error creating plan: {e}")
        raise HTTPException(status_code=500, detail="Failed to create plan")

# Product-related endpoints
@app.post("/add-products")
def add_products(products: List[Product]):
    """Add products to the database"""
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

@app.get("/get-products")
def get_products():
    """Get all products from the database"""
    response = product_table.scan()
    items = response.get("Items", [])
    return [convert_dynamodb_item(item) for item in items]

@app.post("/user-products/{user_id}/{product_id}")
def add_user_product(user_id: str, product_id: int, pri-ce: float):
    """
    Add a product to a user's shop with a custom price.
    Copies product details from the common Products table.
    """
    # Get product from common table
    response = product_table.get_item(Key={'id': product_id})
    if 'Item' not in response:
        raise HTTPException(status_code=404, detail="Product not found")
    product = response['Item']

    # Prepare user product item
    user_product = {
        'user_id': user_id,
        'product_id': product_id,
        'title': product['title'],
        'image': product['image'],
        'price': Decimal(str(price)),  # User's custom price
        'rating': product['rating'],
        'purchases': product['purchases'],
    }
    user_products_table.put_item(Item=user_product)
    return {"message": "Product added to user shop"}

@app.get("/user-products/{user_id}")
def get_user_products(user_id: str):
    """
    Get all products for a user/shop.
    """
    response = user_products_table.query(
        KeyConditionExpression='user_id = :uid',
        ExpressionAttributeValues={':uid': user_id}
    )
    return [convert_dynamodb_item(item) for item in response.get('Items', [])]

@app.put("/user-products/{user_id}/{product_id}")
def update_user_product(user_id: str, product_id: int, price: float):
    """
    Update the price of a user's product.
    """
    user_products_table.update_item(
        Key={'user_id': user_id, 'product_id': product_id},
        UpdateExpression='SET price = :price',
        ExpressionAttributeValues={':price': Decimal(str(price))}
    )
    return {"message": "Product price updated"}

@app.delete("/user-products/{user_id}/{product_id}")
def delete_user_product(user_id: str, product_id: int):
    """
    Delete a product from a user's shop.
    """
    user_products_table.delete_item(
        Key={'user_id': user_id, 'product_id': product_id}
    )
    return {"message": "Product deleted from user shop"}

@app.post("/user-bills/{user_id}")
def save_user_bill(user_id: str, bill: Bill):
    """
    Save a bill to DynamoDB for the given user/shopkeeper.
    """
    # Ensure bill_id and created_at are set if not provided
    from datetime import datetime
    import uuid
    now = datetime.now().isoformat()
    bill_data = bill.dict()
    if not bill_data.get('bill_id'):
        bill_data['bill_id'] = f"bill_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}"
    if not bill_data.get('created_at'):
        bill_data['created_at'] = now
    bill_data['user_id'] = user_id
    # Convert float values to Decimal for DynamoDB
    bill_data['total_amount'] = Decimal(str(bill_data['total_amount']))
    for item in bill_data['items']:
        item['price'] = Decimal(str(item['price']))
        item['total'] = Decimal(str(item['total']))
    user_bills_table.put_item(Item=bill_data)
    return {"message": "Bill saved successfully", "bill_id": bill_data['bill_id']}

@app.get("/user-bills/{user_id}")
def get_user_bills(user_id: str):
    """
    Get all bills for a user/shopkeeper.
    """
    response = user_bills_table.query(
        KeyConditionExpression='user_id = :uid',
        ExpressionAttributeValues={':uid': user_id}
    )
    return [convert_dynamodb_item(item) for item in response.get('Items', [])]

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "AutoBill Registration API"
    }









