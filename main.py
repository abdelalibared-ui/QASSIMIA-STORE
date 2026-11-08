
import json
import os
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from telegram import Bot, MenuButtonWebApp, WebAppInfo
from telegram.ext import Application, CommandHandler

from .db import init_db, connect
from .security import verify_telegram_init_data, require_admin

BASE = Path(__file__).parent
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"
PAYMENT_URL = os.getenv("PAYMENT_URL", "")

telegram_app = None
polling_task = None

async def start_command(update, context):
    keyboard = [[{"text": "🛍️ افتح متجر القاسمية", "web_app": {"url": WEBAPP_URL}}]]
    from telegram import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
    markup = ReplyKeyboardMarkup(
        [[KeyboardButton("🛍️ افتح متجر القاسمية", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True
    )
    await update.message.reply_text(
        "مرحباً بك في متجر القاسمية ✨\nتصفح القشابية والجيلية واختر ما يناسبك.",
        reply_markup=markup
    )

@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_app, polling_task
    init_db()
    if BOT_TOKEN and WEBAPP_URL and "your-domain.example" not in WEBAPP_URL:
        telegram_app = Application.builder().token(BOT_TOKEN).build()
        telegram_app.add_handler(CommandHandler("start", start_command))
        await telegram_app.initialize()
        await telegram_app.start()
        if telegram_app.updater:
            await telegram_app.updater.start_polling()
        try:
            await telegram_app.bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="افتح المتجر", web_app=WebAppInfo(url=WEBAPP_URL))
            )
        except Exception as e:
            print("Could not set Telegram menu button:", e)
    yield
    if telegram_app:
        if telegram_app.updater:
            await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()

app = FastAPI(title="Qassimia Store", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

class ProductIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    category: str = Field(min_length=1, max_length=60)
    description: str = ""
    price_dzd: int = Field(ge=0)
    image_url: str = ""
    colors: list[str] = []
    sizes: list[str] = []
    stock: int = Field(ge=0)

class OrderItemIn(BaseModel):
    product_id: int
    color: str
    size: str
    quantity: int = Field(ge=1, le=20)

class OrderIn(BaseModel):
    customer_name: str = Field(min_length=2, max_length=100)
    phone: str = Field(min_length=8, max_length=30)
    wilaya: str = Field(min_length=2, max_length=80)
    municipality: str = Field(min_length=2, max_length=100)
    address: str = Field(min_length=3, max_length=250)
    notes: str = ""
    payment_method: str
    items: list[OrderItemIn] = Field(min_length=1, max_length=30)

def telegram_user(request: Request):
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if DEV_MODE and not init_data:
        return {"id": "dev-user", "first_name": "Test"}
    user = verify_telegram_init_data(init_data, BOT_TOKEN)
    if not user:
        raise HTTPException(status_code=401, detail="افتح المتجر من تيليجرام لإتمام الطلب.")
    return user

@app.get("/")
def store():
    return FileResponse(BASE / "static" / "index.html")

@app.get("/admin")
def admin():
    return FileResponse(BASE / "static" / "admin.html")

@app.get("/api/config")
def config():
    return {"electronic_payment_enabled": bool(PAYMENT_URL),
            "brand": "القاسمية", "currency": "دج"}

@app.get("/api/products")
def products():
    with connect() as con:
        rows = con.execute("SELECT * FROM products WHERE active=1 ORDER BY id DESC").fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["colors"] = json.loads(d["colors"] or "[]")
            d["sizes"] = json.loads(d["sizes"] or "[]")
            result.append(d)
        return result

@app.post("/api/orders")
async def create_order(payload: OrderIn, request: Request, user=Depends(telegram_user)):
    if payload.payment_method not in (["cod", "electronic"] if PAYMENT_URL else ["cod"]):
        raise HTTPException(status_code=400, detail="طريقة الدفع غير متاحة حالياً.")
    with connect() as con:
        subtotal = 0
        validated = []
        for item in payload.items:
            product = con.execute("SELECT * FROM products WHERE id=? AND active=1", (item.product_id,)).fetchone()
            if not product:
                raise HTTPException(status_code=400, detail="أحد المنتجات غير متوفر.")
            colors = json.loads(product["colors"] or "[]")
            sizes = json.loads(product["sizes"] or "[]")
            if item.color not in colors or item.size not in sizes:
                raise HTTPException(status_code=400, detail="اللون أو المقاس غير صالح.")
            if product["price_dzd"] <= 0:
                raise HTTPException(status_code=400, detail="يرجى التواصل معنا لتأكيد سعر هذا المنتج.")
            if product["stock"] < item.quantity:
                raise HTTPException(status_code=400, detail=f"الكمية غير متوفرة للمنتج: {product['name']}")
            subtotal += product["price_dzd"] * item.quantity
            validated.append((product, item))
        # Delivery fee is configurable in a later version; zero here until the merchant sets it.
        delivery_fee = 0
        cur = con.execute("""INSERT INTO orders
            (customer_name, phone, wilaya, municipality, address, notes, payment_method,
             subtotal_dzd, delivery_fee_dzd, total_dzd, telegram_user_id)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (payload.customer_name, payload.phone, payload.wilaya, payload.municipality,
             payload.address, payload.notes, payload.payment_method, subtotal,
             delivery_fee, subtotal + delivery_fee, str(user.get("id", ""))))
        order_id = cur.lastrowid
        for product, item in validated:
            con.execute("""INSERT INTO order_items
                (order_id, product_id, product_name, color, size, quantity, unit_price_dzd)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (order_id, product["id"], product["name"], item.color, item.size,
                 item.quantity, product["price_dzd"]))
            con.execute("UPDATE products SET stock=stock-? WHERE id=?",
                        (item.quantity, product["id"]))
    if telegram_app and os.getenv("ADMIN_CHAT_ID"):
        try:
            await telegram_app.bot.send_message(
                chat_id=os.getenv("ADMIN_CHAT_ID"),
                text=f"🛍️ طلب جديد #{order_id}\nالاسم: {payload.customer_name}\nالهاتف: {payload.phone}\nالولاية: {payload.wilaya}\nالبلدية: {payload.municipality}\nالإجمالي: {subtotal} دج\nالدفع: {'عند الاستلام' if payload.payment_method == 'cod' else 'إلكتروني'}"
            )
        except Exception as e:
            print("Admin notification failed:", e)
    response = {"ok": True, "order_id": order_id, "total_dzd": subtotal + delivery_fee}
    if payload.payment_method == "electronic" and PAYMENT_URL:
        response["payment_url"] = PAYMENT_URL
    return response

@app.get("/api/admin/summary")
def admin_summary(request: Request):
    require_admin(request)
    with connect() as con:
        orders = con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        revenue = con.execute("SELECT COALESCE(SUM(total_dzd),0) FROM orders WHERE status IN ('مكتمل','تم الشحن')").fetchone()[0]
        new_orders = con.execute("SELECT COUNT(*) FROM orders WHERE status='جديد'").fetchone()[0]
        products = con.execute("SELECT COUNT(*) FROM products WHERE active=1").fetchone()[0]
        return {"orders": orders, "revenue": revenue, "new_orders": new_orders, "products": products}

@app.get("/api/admin/products")
def admin_products(request: Request):
    require_admin(request)
    with connect() as con:
        rows = con.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]

@app.post("/api/admin/products")
def add_product(payload: ProductIn, request: Request):
    require_admin(request)
    with connect() as con:
        cur = con.execute("""INSERT INTO products
            (name,category,description,price_dzd,image_url,colors,sizes,stock)
            VALUES (?,?,?,?,?,?,?,?)""",
            (payload.name,payload.category,payload.description,payload.price_dzd,payload.image_url,
             json.dumps(payload.colors, ensure_ascii=False),json.dumps(payload.sizes, ensure_ascii=False),payload.stock))
        return {"ok": True, "id": cur.lastrowid}

@app.put("/api/admin/products/{product_id}")
def update_product(product_id: int, payload: ProductIn, request: Request):
    require_admin(request)
    with connect() as con:
        cur = con.execute("""UPDATE products SET name=?,category=?,description=?,price_dzd=?,
            image_url=?,colors=?,sizes=?,stock=? WHERE id=?""",
            (payload.name,payload.category,payload.description,payload.price_dzd,payload.image_url,
             json.dumps(payload.colors, ensure_ascii=False),json.dumps(payload.sizes, ensure_ascii=False),
             payload.stock,product_id))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="المنتج غير موجود")
        return {"ok": True}

@app.get("/api/admin/orders")
def admin_orders(request: Request):
    require_admin(request)
    with connect() as con:
        orders = con.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 300").fetchall()
        result = []
        for order in orders:
            d = dict(order)
            d["items"] = [dict(x) for x in con.execute("SELECT * FROM order_items WHERE order_id=?", (d["id"],)).fetchall()]
            result.append(d)
        return result

@app.patch("/api/admin/orders/{order_id}")
def update_order(order_id: int, request: Request, status: str):
    require_admin(request)
    allowed = ["جديد", "بانتظار التأكيد", "قيد التجهيز", "تم الشحن", "مكتمل", "ملغى"]
    if status not in allowed:
        raise HTTPException(status_code=400, detail="حالة غير صحيحة")
    with connect() as con:
        cur = con.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="الطلب غير موجود")
        return {"ok": True}
