import os
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

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
            secure=False,  # В продакшене → True + HTTPS
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
        "current_user_email": user.email if user else None
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


# ── Предложить предмет в вишлист ─────────────────────────────────────────
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


# ── Просмотр предложений для своего вишлиста ─────────────────────────────
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)