"""Site shell (head, top bar, navigation, alerts, footer) built with FastHTML + MonsterUI.

FastHTML's FT components and MonsterUI (FrankenUI + Tailwind) render the layout
pieces to HTML, which the existing Jinja templates drop in. The FastAPI routes,
forms and page content stay exactly as they were; only the look changes.
"""

from __future__ import annotations

from typing import Any

from fasthtml.common import (
    A,
    Aside,
    Details,
    Div,
    Footer,
    Form,
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
    Alert,
    AlertT,
    Button,
    ButtonT,
    NavContainer,
    NavHeaderLi,
    NavT,
    Theme,
    UkIcon,
)

CSS_VERSION = "fh1"

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
            items.append(Li(A(label, href=f"/servers/{guild.id}{path}"), cls="uk-active" if key == active else ""))
    if is_admin:
        items.append(NavHeaderLi("Admin"))
        items.append(Li(A("Admin", href="/admin")))
    items.append(NavHeaderLi("Servers"))
    items.append(Li(A(all_label, href="/servers")))
    return NavContainer(*items, cls=(NavT.secondary, "site-nav"))


def topbar(user: dict | None = None, guild: Any = None, is_admin: bool = False, avatar_url: str | None = None, csrf_token: str = "") -> Markup:
    brand = A(
        Span(UkIcon("gamepad-2", height=18, width=18), cls="brand-mark"),
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
            Nav(_nav_list(guild, active, is_admin, all_label="← All servers"), cls="nav", aria_label="Server panels"),
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


def install(env: Any) -> None:
    """Make the FastHTML/MonsterUI shell available to every Jinja template."""
    env.globals["ui"] = _UI
