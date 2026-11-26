"""Site shell (head, top bar, navigation, alerts, footer) built with FastHTML + MonsterUI.

FastHTML's FT components and MonsterUI (FrankenUI + Tailwind) render the layout
pieces to HTML, which the existing Jinja templates drop in. The FastAPI routes,
forms and page content stay exactly as they were; only the look changes.
"""

from __future__ import annotations

from typing import Any

from fasthtml.common import (
    A,
    P,
    Section,
    Aside,
    Details,
    Div,
    Footer,
    Form,
    Code,
    Header,
    Img,
    Input,
    Li,
    Link,
    Nav,
    Span,
    Strong,
    Summary,
    to_xml,
)
from markupsafe import Markup
from monsterui.all import (
    H1,
    H3,
    Alert,
    AlertT,
    Button,
    ButtonT,
    Card,
    DivLAligned,
    Grid,
    Label,
    LabelT,
    NavContainer,
    NavHeaderLi,
    NavT,
    Theme,
    UkIcon,
)

CSS_VERSION = "fh2"

# (group, [(active key, label, path under /servers/{id})])
NAV_GROUPS: tuple[tuple[str, tuple[tuple[str, str, str], ...]], ...] = (
    ("Overview", (("overview", "Overview", ""),)),
    ("Moderation & Safety", (
        ("moderation", "Moderation", "/moderation"),
        ("alts", "Alt detection", "/alts"),
        ("reports", "Reports", "/reports"),
        ("auditlogs", "Audit Logs", "/auditlogs"),
    )),
    ("Roles", (("customroles", "Custom Roles", "/customroles"), ("selfroles", "Self roles", "/selfroles"))),
    ("Community", (
        ("levels", "Levels", "/levels"),
        ("welcome", "Messages", "/welcome"),
        ("games", "Games", "/games"),
        ("channels", "Channels", "/channels"),
    )),
    ("Creator Integration", (("youtube", "Creator Integration", "/youtube"),)),
    ("Premium & Billing", (("billing", "Billing", "/billing"),)),
)


NAV_ICONS = {
    "overview": "layout-dashboard",
    "moderation": "shield",
    "alts": "user-search",
    "reports": "flag",
    "auditlogs": "scroll-text",
    "customroles": "palette",
    "selfroles": "mouse-pointer-click",
    "levels": "trophy",
    "welcome": "message-square",
    "games": "gamepad-2",
    "channels": "hash",
    "youtube": "youtube",
    "billing": "credit-card",
    "admin": "settings",
    "servers": "arrow-left",
}


def _icon(key: str, size: int = 16) -> Any:
    return UkIcon(NAV_ICONS.get(key, "circle"), height=size, width=size, cls="nav-icon")


def _html(*parts: Any) -> Markup:
    return Markup("".join(to_xml(p) for p in parts if p is not None))


def head() -> Markup:
    """MonsterUI theme headers (FrankenUI CSS/JS, Tailwind, icons) plus the site stylesheet."""
    hdrs = Theme.blue.headers(mode="dark", daisy=False, radii="uk-radii-md", shadows="uk-shadows-sm", font="uk-font-sm")
    return _html(*hdrs, Link(rel="stylesheet", href=f"/static/site.css?v={CSS_VERSION}"))


def active_label(active: str | None) -> str:
    for _group, items in NAV_GROUPS:
        for key, label, _path in items:
            if key == active:
                return label
    return "Menu"


def _nav_list(guild: Any, active: str | None, is_admin: bool, *, all_label: str) -> Any:
    items: list[Any] = []
    for group, links in NAV_GROUPS:
        items.append(NavHeaderLi(group))
        for key, label, path in links:
            items.append(Li(A(_icon(key), Span(label), href=f"/servers/{guild.id}{path}"), cls="uk-active" if key == active else ""))
    if is_admin:
        items.append(NavHeaderLi("Admin"))
        items.append(Li(A(_icon("admin"), Span("Admin"), href="/admin")))
    items.append(NavHeaderLi("Servers"))
    items.append(Li(A(_icon("servers"), Span(all_label), href="/servers")))
    return NavContainer(*items, cls=(NavT.secondary, "site-nav"))


def topbar(user: dict | None = None, guild: Any = None, is_admin: bool = False, avatar_url: str | None = None, csrf_token: str = "") -> Markup:
    brand = A(
        Span(UkIcon("coffee", height=17, width=17), cls="brand-mark"),
        Span("Meowchi Cafe"),
        cls="brand",
        href="/servers" if user else "/",
    )
    left: list[Any] = [brand]
    if guild is not None:
        left += [Span("/", cls="crumb-sep"), Strong(guild.name, cls="crumb-guild")]
    right: list[Any] = [A("Pricing", href="/pricing", cls="top-link")]
    if is_admin:
        right.append(A("Admin", href="/admin", cls="top-link"))
    if user:
        chip: list[Any] = []
        if avatar_url:
            chip.append(Img(src=avatar_url, alt=""))
        chip.append(Span(user.get("username", "")))
        right.append(Span(*chip, cls="user-chip"))
        right.append(
            Form(
                Input(type="hidden", name="csrf_token", value=csrf_token),
                Button("Log out", cls=(ButtonT.secondary, ButtonT.sm)),
                method="post",
                action="/logout",
                cls="logout-form",
            )
        )
    return _html(Header(Div(*left, cls="topbar-left"), Div(*right, cls="topbar-right"), cls="topbar"))


def mobile_nav(guild: Any, active: str | None, is_admin: bool = False) -> Markup:
    return _html(
        Div(
            Details(
                Summary(
                    Span("Menu", cls="mnav-label"),
                    Span(active_label(active), cls="mnav-current"),
                    UkIcon("chevron-down", height=16, width=16, cls="mnav-chev"),
                ),
                Nav(_nav_list(guild, active, is_admin, all_label="All servers"), cls="mnav-body", aria_label="Server panels"),
                cls="mnav",
                id="panel-menu",
            ),
            cls="mobile-nav",
        )
    )


def sidebar(guild: Any, active: str | None, is_admin: bool = False) -> Markup:
    return _html(
        Aside(
            Div(guild.name, cls="sidebar-guild"),
            Nav(_nav_list(guild, active, is_admin, all_label="All servers"), cls="nav", aria_label="Server panels"),
            cls="sidebar",
        )
    )


def flash(kind: str, message: str) -> Markup:
    cls = AlertT.success if kind == "ok" else AlertT.error
    return _html(Alert(message, cls=(cls, "flash", kind)))


def upgrade_banner(pricing_url: str) -> Markup:
    return _html(
        Alert(
            "This server needs Meowchi Cafe Premium — ",
            A("subscribe at the pricing page", href=pricing_url),
            ".",
            cls=(AlertT.warning, "flash", "error", "upgrade-banner"),
        )
    )


def footer() -> Markup:
    return _html(
        Footer(
            Nav(
                Div(Div("Product", cls="footer-title"), A("Pricing", href="/pricing"), A("Your servers", href="/servers"), cls="footer-col"),
                Div(
                    Div("Legal & contact", cls="footer-title"),
                    A("Contact", href="/contact"),
                    A("Privacy", href="/privacy"),
                    A("Terms", href="/terms"),
                    cls="footer-col",
                ),
                cls="footer-groups",
                aria_label="Site",
            ),
            Div("Made by Whiskey/WarRaven", cls="footer-credit"),
            cls="site-footer",
        )
    )


# ---------- page building blocks (MonsterUI) ----------

FEATURES: tuple[tuple[str, str, str], ...] = (
    ("shield", "Moderation & Safety", "Mod log, warnings, alt detection, member reports and per-event audit logs sent to the channel you pick."),
    ("trophy", "Levels", "XP from chat and voice, level roles, a leaderboard, and a master switch so it never clashes with another levelling bot."),
    ("youtube", "Creator Integration", "Post an alert the moment a YouTube channel uploads, with your own message and @everyone, role or no ping."),
    ("palette", "Roles", "Member-made custom roles with gradients, plus button self-roles for your community."),
    ("message-square", "Messages", "Welcome, leave and ban messages with placeholders, all edited from one screen."),
    ("gamepad-2", "Games & channels", "Games, counting and every assigned channel in one place, no slash commands needed."),
)


def landing(login_disabled: bool = False, oauth_ready: bool = True) -> Markup:
    """Public home page, built entirely from FastHTML + MonsterUI components."""
    if login_disabled or not oauth_ready:
        cta: Any = P(
            "Login is not configured on this instance yet. Set ", Code("DISCORD_CLIENT_SECRET"), ", ",
            Code("DASHBOARD_URL"), ", and ", Code("SESSION_SECRET"),
            ", and add the redirect URL in the Discord Developer Portal under OAuth2 → Redirects.",
            cls="muted",
        )
    else:
        cta = Div(
            A(UkIcon("log-in", height=16, width=16), Span("Log in with Discord"), href="/login", cls=(ButtonT.primary, "uk-btn", "btn", "btn-lg")),
            A("See pricing", href="/pricing", cls=(ButtonT.ghost, "uk-btn", "btn-lg", "btn-ghost")),
            cls="hero-actions",
        )
    hero = Section(
        Label("Meowchi Cafe dashboard", cls=(LabelT.primary, "hero-badge")),
        H1("Manage your servers from one place", cls="hero-title"),
        P(
            "Assign channels, tweak levels and welcome messages, control games, and review alt-detection — "
            "all without digging through slash commands. Built for phones as well as desktops.",
            cls="hero-sub",
        ),
        cta,
        cls="hero-x",
    )
    cards = [
        Card(
            DivLAligned(Span(UkIcon(icon, height=18, width=18), cls="feat-icon"), H3(title, cls="feat-title")),
            P(text, cls="feat-text"),
            cls="feat-card",
        )
        for icon, title, text in FEATURES
    ]
    features = Section(
        Div(Div("Everything in one dashboard", cls="section-title"), P("Every setting the bot has, grouped the way you think about your server.", cls="muted"), cls="section-head"),
        Grid(*cards, cols_sm=1, cols_md=2, cols_lg=3, cols_xl=3, gap=4),
        cls="features-x",
    )
    steps = Section(
        Div(Div("Up and running in a minute", cls="section-title"), cls="section-head"),
        Grid(
            *[
                Div(Span(str(i), cls="step-num"), Div(t, cls="step-title"), P(d, cls="muted"), cls="step-x")
                for i, (t, d) in enumerate(
                    (
                        ("Log in with Discord", "We only see servers where you have Manage Server."),
                        ("Pick a server", "Invite the bot if it is not there yet."),
                        ("Change settings", "Saved instantly — the bot picks them up right away."),
                    ),
                    start=1,
                )
            ],
            cols_sm=1, cols_md=3, cols_lg=3, cols_xl=3, gap=4,
        ),
        cls="steps-x",
    )
    return _html(Div(hero, features, steps, cls="landing"))


def page_head(title: str, subtitle: str = "", icon: str | None = None) -> Markup:
    parts: list[Any] = []
    if icon:
        parts.append(Span(UkIcon(NAV_ICONS.get(icon, icon), height=20, width=20), cls="page-icon"))
    parts.append(Div(H1(title, cls="page-title"), P(subtitle, cls="lede") if subtitle else None))
    return _html(Div(*parts, cls="page-head"))


def stat(value: Any, label: str, icon: str) -> Markup:
    return _html(
        Card(
            Div(
                Div(Div(str(value), cls="stat"), Div(label, cls="stat-label")),
                Span(UkIcon(icon, height=18, width=18), cls="stat-icon"),
                cls="stat-row",
            ),
            cls="stat-card",
        )
    )


def cat_icon(key: str) -> Markup:
    return _html(Span(UkIcon(NAV_ICONS.get(key, key), height=18, width=18), cls="cat-icon"))


class _UI:
    """Namespace exposed to Jinja as `ui`."""

    head = staticmethod(head)
    topbar = staticmethod(topbar)
    mobile_nav = staticmethod(mobile_nav)
    sidebar = staticmethod(sidebar)
    flash = staticmethod(flash)
    upgrade_banner = staticmethod(upgrade_banner)
    footer = staticmethod(footer)
    active_label = staticmethod(active_label)
    landing = staticmethod(landing)
    page_head = staticmethod(page_head)
    stat = staticmethod(stat)
    cat_icon = staticmethod(cat_icon)


def install(env: Any) -> None:
    """Make the FastHTML/MonsterUI shell available to every Jinja template."""
    env.globals["ui"] = _UI
