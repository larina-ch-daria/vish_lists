import os
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from supabase import create_client, Client
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv


load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    raise ValueError("SUPABASE_URL и SUPABASE_ANON_KEY должны быть в .env")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

app = FastAPI(title="Wishlist App")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


def get_current_user(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        response = supabase.auth.get_user(token)
        return response.user
    except Exception:
        return None


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login")
    return RedirectResponse("/wishlist")


# ── Аутентификация ───────────────────────────────────────────────────────
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...)):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        if not res.session:
            raise Exception("Не удалось войти")
        response = RedirectResponse("/wishlist", status_code=303)
        response.set_cookie(
            key="access_token",
            value=res.session.access_token,
            httponly=True,
            max_age=res.session.expires_in,
            secure=False,
            samesite="lax"
        )
        return response
    except Exception as e:
        msg = "Неверный email или пароль" if "invalid" in str(e).lower() else str(e)
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": msg}, status_code=400
        )


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@app.post("/register")
async def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...)
):
    if password != password_confirm:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Пароли не совпадают"},
            status_code=400
        )
    try:
        supabase.auth.sign_up({"email": email, "password": password})
        return templates.TemplateResponse(
            "register_success.html",
            {"request": request, "email": email}
        )
    except Exception as e:
        msg = "Пользователь уже существует" if "duplicate" in str(e).lower() else str(e)
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": msg},
            status_code=400
        )


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/login")
    resp.delete_cookie("access_token")
    return resp


# ── Публичные списки ─────────────────────────────────────────────────────
@app.get("/public", response_class=HTMLResponse)
async def public_wishlists(request: Request):
    result = (
        supabase.table("wishlists")
        .select("id, title, description, created_at, user_id")
        .eq("is_shared", True)
        .order("created_at", desc=True)
        .execute()
    )
    
    return templates.TemplateResponse(
        "public_wishlists.html",
        {
            "request": request,
            "wishlists": result.data or []
        }
    )


# ── Календарь праздников ──────────────────────────────────────────────────
@app.get("/calendar", response_class=HTMLResponse)
async def calendar_view(request: Request, month: int = None, year: int = None):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login")

    today = datetime.now()
    target_month = month or today.month
    target_year = year or today.year

    start_date = date(target_year, target_month, 1)
    end_date = start_date + relativedelta(months=1) - relativedelta(days=1)

    holidays_res = supabase.table("holidays")\
        .select("id, title, date, description")\
        .eq("user_id", user.id)\
        .gte("date", start_date.isoformat())\
        .lte("date", end_date.isoformat())\
        .order("date")\
        .execute()

    calendar_data = {}
    for h in holidays_res.data or []:
        d = h["date"]
        if d not in calendar_data:
            calendar_data[d] = []

        links_res = supabase.table("holiday_wishlists")\
            .select("wishlist_id, wishlists(title)")\
            .eq("holiday_id", h["id"])\
            .execute()

        h["holiday_wishlists"] = links_res.data or []
        calendar_data[d].append(h)

    return templates.TemplateResponse("calendar.html", {
        "request": request,
        "current_month": target_month,
        "current_year": target_year,
        "calendar_data": calendar_data,
        "prev_month": (start_date - relativedelta(months=1)).strftime("%Y-%m"),
        "next_month": (start_date + relativedelta(months=1)).strftime("%Y-%m")
    })


# ── API для календаря (цветные точки) ─────────────────────────────────────
@app.get("/calendar/events/{year}/{month}")
async def get_calendar_events(year: int, month: int, request: Request):
    user = get_current_user(request)
    if not user:
        return {}

    start = date(year, month, 1)
    end = start + relativedelta(months=1) - relativedelta(days=1)

    res = supabase.table("holidays")\
        .select("date, holiday_wishlists(count)")\
        .eq("user_id", user.id)\
        .gte("date", start.isoformat())\
        .lte("date", end.isoformat())\
        .execute()

    counts = {}
    for h in res.data or []:
        day = h["date"].split('-')[2].lstrip('0')
        counts[day] = h["holiday_wishlists"][0]["count"]

    return counts


@app.get("/calendar/add", response_class=HTMLResponse)
async def add_holiday_form(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login")

    wishlists_res = supabase.table("wishlists")\
        .select("id, title")\
        .eq("user_id", user.id)\
        .execute()

    return templates.TemplateResponse("add_holiday.html", {
        "request": request,
        "wishlists": wishlists_res.data or [],
        "preselected_date": request.query_params.get("date")
    })


@app.post("/calendar/add")
async def add_holiday(
    request: Request,
    title: str = Form(...),
    date_str: str = Form(...),
    description: str = Form(None),
    wishlist_ids: list[str] = Form(None)
):
    user = get_current_user(request)
    if not user:
        raise HTTPException(401)

    try:
        holiday_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except:
        raise HTTPException(400, "Неверный формат даты (YYYY-MM-DD)")

    holiday_res = supabase.table("holidays").insert({
        "user_id": user.id,
        "title": title.strip(),
        "date": holiday_date.isoformat(),
        "description": description.strip() if description else None
    }).execute()

    holiday_id = holiday_res.data[0]["id"]

    if wishlist_ids:
        valid_res = supabase.table("wishlists")\
            .select("id")\
            .eq("user_id", user.id)\
            .in_("id", wishlist_ids)\
            .execute()

        valid_ids = {w["id"] for w in valid_res.data or []}

        for wid in wishlist_ids:
            if wid in valid_ids:
                supabase.table("holiday_wishlists").insert({
                    "holiday_id": holiday_id,
                    "wishlist_id": wid
                }).execute()
            else:
                print(f"Пропущен недействительный wishlist_id: {wid}")

    return RedirectResponse("/calendar", status_code=303)


# ── Поделиться вишлистом через Telegram ──────────────────────────────────
@app.get("/share-via-telegram", response_class=HTMLResponse)
async def share_via_telegram_form(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login")

    wishlists = supabase.table("wishlists")\
        .select("id, title")\
        .eq("user_id", user.id)\
        .execute()

    return templates.TemplateResponse("share_telegram_simple.html", {
        "request": request,
        "wishlists": wishlists.data or []
    })


@app.post("/share-via-telegram")
async def generate_telegram_link(
    request: Request,
    wishlist_id: str = Form(...),
    telegram_username: str = Form(...)
):
    user = get_current_user(request)
    if not user:
        raise HTTPException(401)

    # Проверяем вишлист
    wl = supabase.table("wishlists")\
        .select("id, title, is_shared")\
        .eq("id", wishlist_id)\
        .eq("user_id", user.id)\
        .single()\
        .execute()

    if not wl.data:
        raise HTTPException(404, "Вишлист не найден или не ваш")

    wishlist = wl.data

    # Делаем публичным
    if not wishlist["is_shared"]:
        supabase.table("wishlists")\
            .update({"is_shared": True})\
            .eq("id", wishlist_id)\
            .execute()

    # Формируем ссылку на вишлист
    base_url = str(request.base_url).rstrip('/')
    wishlist_link = f"{base_url}/wishlist/{wishlist_id}"

    # Текст сообщения
    message = (
        f"Привет! 🎁\n\n"
        f"Вот мой вишлист: «{wishlist['title']}»\n"
        f"Ссылка: {wishlist_link}\n\n"
        f"Можешь выбрать, что подарить 😊"
    )

    # Экранируем для URL
    import urllib.parse
    encoded_message = urllib.parse.quote(message)

    # Прямая ссылка на Telegram
    telegram_link = f"https://t.me/{telegram_username.strip().lstrip('@')}?text={encoded_message}"

    return RedirectResponse(telegram_link, status_code=303)


# ── Мои списки ───────────────────────────────────────────────────────────
@app.get("/wishlist", response_class=HTMLResponse)
async def my_wishlists(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login")

    result = supabase.table("wishlists")\
        .select("*")\
        .eq("user_id", user.id)\
        .order("created_at", desc=True)\
        .execute()

    return templates.TemplateResponse("wishlist.html", {
        "request": request,
        "wishlists": result.data or [],
        "user_email": user.email
    })


@app.post("/wishlist/create")
async def create_wishlist(request: Request, title: str = Form(...), description: str = Form(None)):
    user = get_current_user(request)
    if not user:
        raise HTTPException(401)

    supabase.table("wishlists").insert({
        "user_id": user.id,
        "title": title.strip(),
        "description": description.strip() if description else None
    }).execute()

    return RedirectResponse("/wishlist", status_code=303)


# ── Детальная страница вишлиста ──────────────────────────────────────────
@app.get("/wishlist/{wishlist_id}", response_class=HTMLResponse)
async def view_wishlist(request: Request, wishlist_id: str):
    user = get_current_user(request)

    wl_res = supabase.table("wishlists").select("*").eq("id", wishlist_id).execute()
    if not wl_res.data:
        raise HTTPException(404, "Список не найден")

    wishlist = wl_res.data[0]

    is_owner = user and str(user.id) == str(wishlist["user_id"])
    can_view = is_owner or wishlist.get("is_shared", False)

    if not can_view:
        raise HTTPException(403, "Нет доступа к этому списку")

    items_res = supabase.table("wishlist_items")\
        .select("*")\
        .eq("wishlist_id", wishlist_id)\
        .order("priority", desc=True)\
        .order("created_at")\
        .execute()

    return templates.TemplateResponse("wishlist_detail.html", {
        "request": request,
        "wishlist": wishlist,
        "items": items_res.data or [],
        "is_owner": is_owner,
        "current_user_email": user.email if user else None,
        "current_user_id": str(user.id) if user else None
    })


@app.post("/wishlist/{wishlist_id}/toggle-share")
async def toggle_share(request: Request, wishlist_id: str):
    user = get_current_user(request)
    if not user:
        raise HTTPException(401)

    wl = supabase.table("wishlists")\
        .select("user_id, is_shared")\
        .eq("id", wishlist_id)\
        .eq("user_id", user.id)\
        .single()\
        .execute()

    if not wl.data:
        raise HTTPException(403, "Это не ваш список")

    new_state = not wl.data["is_shared"]

    supabase.table("wishlists")\
        .update({"is_shared": new_state})\
        .eq("id", wishlist_id)\
        .execute()

    return RedirectResponse(f"/wishlist/{wishlist_id}", status_code=303)


@app.post("/wishlist/{wishlist_id}/add-item")
async def add_item(
    request: Request,
    wishlist_id: str,
    title: str = Form(...),
    description: str = Form(None),
    url: str = Form(None),
    price: float = Form(None),
    currency: str = Form("€"),
    priority: int = Form(3, ge=1, le=5)
):
    user = get_current_user(request)
    if not user:
        raise HTTPException(401)

    wl = supabase.table("wishlists")\
        .select("user_id")\
        .eq("id", wishlist_id)\
        .single()\
        .execute()

    if not wl.data or str(wl.data["user_id"]) != str(user.id):
        raise HTTPException(403, "Добавлять можно только в свои списки")

    supabase.table("wishlist_items").insert({
        "wishlist_id": wishlist_id,
        "title": title.strip(),
        "description": description.strip() if description else None,
        "url": url.strip() if url else None,
        "price": price,
        "currency": currency,
        "priority": priority
    }).execute()

    return RedirectResponse(f"/wishlist/{wishlist_id}", status_code=303)


# ── Предложить предмет ────────────────────────────────────────────────────
@app.get("/wishlist/{wishlist_id}/suggest", response_class=HTMLResponse)
async def suggest_form(request: Request, wishlist_id: str):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login")

    wl_res = supabase.table("wishlists")\
        .select("id, title, user_id, is_shared")\
        .eq("id", wishlist_id)\
        .single()\
        .execute()

    if not wl_res.data:
        raise HTTPException(404, "Список не найден")

    wishlist = wl_res.data

    if not (wishlist["is_shared"] or str(wishlist["user_id"]) == str(user.id)):
        raise HTTPException(403, "Нельзя предлагать предметы в этот список")

    return templates.TemplateResponse("suggest_item.html", {
        "request": request,
        "wishlist_id": wishlist_id,
        "wishlist_title": wishlist["title"]
    })


@app.post("/wishlist/{wishlist_id}/suggest")
async def submit_suggestion(
    request: Request,
    wishlist_id: str,
    title: str = Form(...),
    description: str = Form(None),
    url: str = Form(None),
    price: float = Form(None),
    currency: str = Form("€"),
    comment: str = Form(None)
):
    user = get_current_user(request)
    if not user:
        raise HTTPException(401)

    supabase.table("wishlist_suggestions").insert({
        "wishlist_id": wishlist_id,
        "suggested_by": user.id,
        "title": title.strip(),
        "description": description.strip() if description else None,
        "url": url.strip() if url else None,
        "price": price,
        "currency": currency,
        "comment": comment.strip() if comment else None,
        "status": "pending"
    }).execute()

    return RedirectResponse(f"/wishlist/{wishlist_id}", status_code=303)


# ── Просмотр предложений ──────────────────────────────────────────────────
@app.get("/wishlist/{wishlist_id}/suggestions", response_class=HTMLResponse)
async def view_suggestions(request: Request, wishlist_id: str):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login")

    wl = supabase.table("wishlists")\
        .select("user_id, title")\
        .eq("id", wishlist_id)\
        .single()\
        .execute()

    if not wl.data or str(wl.data["user_id"]) != str(user.id):
        raise HTTPException(403, "Это не ваш список")

    suggestions = supabase.table("wishlist_suggestions")\
        .select("*")\
        .eq("wishlist_id", wishlist_id)\
        .order("created_at", desc=True)\
        .execute()

    return templates.TemplateResponse("wishlist_suggestions.html", {
        "request": request,
        "wishlist_id": wishlist_id,
        "wishlist_title": wl.data["title"],
        "suggestions": suggestions.data or []
    })


@app.post("/wishlist/{wishlist_id}/suggestions/{suggestion_id}/accept")
async def accept_suggestion(request: Request, wishlist_id: str, suggestion_id: str):
    user = get_current_user(request)
    if not user:
        raise HTTPException(401)

    # Проверяем, что это список владельца
    wl = supabase.table("wishlists")\
        .select("user_id")\
        .eq("id", wishlist_id)\
        .single()\
        .execute()

    if not wl.data or str(wl.data["user_id"]) != str(user.id):
        raise HTTPException(403, "Это не ваш список")

    # Получаем само предложение
    sug = supabase.table("wishlist_suggestions")\
        .select("*")\
        .eq("id", suggestion_id)\
        .eq("wishlist_id", wishlist_id)\
        .single()\
        .execute()

    if not sug.data:
        raise HTTPException(404, "Предложение не найдено")

    suggestion = sug.data

    # Вот здесь: создаём новую запись в wishlist_items
    # и обязательно сохраняем, кто предложил (suggested_by)
    supabase.table("wishlist_items").insert({
        "wishlist_id": wishlist_id,
        "title": suggestion["title"],
        "description": suggestion.get("description"),
        "url": suggestion.get("url"),
        "price": suggestion.get("price"),
        "currency": suggestion.get("currency", "€"),
        "priority": 3,  # можно сделать динамическим
        "suggested_by": suggestion["suggested_by"]  # ← кто предложил
    }).execute()

    # Меняем статус предложения на accepted
    supabase.table("wishlist_suggestions")\
        .update({"status": "accepted"})\
        .eq("id", suggestion_id)\
        .execute()

    return RedirectResponse(f"/wishlist/{wishlist_id}/suggestions", status_code=303)

@app.post("/wishlist/{wishlist_id}/delete")
async def delete_wishlist(request: Request, wishlist_id: str):
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "Необходима авторизация")

    # Проверяем, что список принадлежит пользователю
    wl = supabase.table("wishlists")\
        .select("user_id")\
        .eq("id", wishlist_id)\
        .eq("user_id", user.id)\
        .single()\
        .execute()

    if not wl.data:
        raise HTTPException(403, "Это не ваш список или список не найден")

    # Удаляем список (каскадно удалятся все связанные записи: items, suggestions, holiday_wishlists и т.д.)
    supabase.table("wishlists")\
        .delete()\
        .eq("id", wishlist_id)\
        .execute()

    return RedirectResponse("/wishlist", status_code=303)

@app.post("/wishlist/{wishlist_id}/suggestions/{suggestion_id}/reject")
async def reject_suggestion(request: Request, wishlist_id: str, suggestion_id: str):
    user = get_current_user(request)
    if not user:
        raise HTTPException(401)

    wl = supabase.table("wishlists")\
        .select("user_id")\
        .eq("id", wishlist_id)\
        .single()\
        .execute()

    if not wl.data or str(wl.data["user_id"]) != str(user.id):
        raise HTTPException(403, "Это не ваш список")

    supabase.table("wishlist_suggestions")\
        .update({"status": "rejected"})\
        .eq("id", suggestion_id)\
        .execute()

    return RedirectResponse(f"/wishlist/{wishlist_id}/suggestions", status_code=303)


# ── Бронирование подарка ──────────────────────────────────────────────────
@app.post("/wishlist/{wishlist_id}/item/{item_id}/reserve")
async def reserve_item(request: Request, wishlist_id: str, item_id: str):
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "Нужно войти в аккаунт")

    item = supabase.table("wishlist_items")\
        .select("id, wishlist_id, reserved_by")\
        .eq("id", item_id)\
        .eq("wishlist_id", wishlist_id)\
        .single()\
        .execute()

    if not item.data:
        raise HTTPException(404, "Подарок не найден")

    if item.data["reserved_by"]:
        raise HTTPException(400, "Этот подарок уже забронирован")

    supabase.table("wishlist_items")\
        .update({
            "reserved_by": user.id,
            "reserved_at": "now()"
        })\
        .eq("id", item_id)\
        .execute()

    return RedirectResponse(f"/wishlist/{wishlist_id}", status_code=303)


@app.post("/wishlist/{wishlist_id}/item/{item_id}/unreserve")
async def unreserve_item(request: Request, wishlist_id: str, item_id: str):
    user = get_current_user(request)
    if not user:
        raise HTTPException(401)

    item = supabase.table("wishlist_items")\
        .select("id, wishlist_id, reserved_by")\
        .eq("id", item_id)\
        .eq("wishlist_id", wishlist_id)\
        .single()\
        .execute()

    if not item.data:
        raise HTTPException(404)

    wl = supabase.table("wishlists")\
        .select("user_id")\
        .eq("id", wishlist_id)\
        .single()\
        .execute()

    is_owner = str(wl.data["user_id"]) == str(user.id)
    is_reserver = str(item.data["reserved_by"]) == str(user.id)

    if not (is_owner or is_reserver):
        raise HTTPException(403, "Нет прав на отмену брони")

    supabase.table("wishlist_items")\
        .update({
            "reserved_by": None,
            "reserved_at": None
        })\
        .eq("id", item_id)\
        .execute()

    return RedirectResponse(f"/wishlist/{wishlist_id}", status_code=303)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)