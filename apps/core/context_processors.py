"""The app shell's navigation, shared by the sidebar, tab bar and More sheet."""

from typing import TYPE_CHECKING, Any

from django.urls import reverse

if TYPE_CHECKING:
    from django.http import HttpRequest

# The first TAB_COUNT nav items get a phone tab; the rest live in the More sheet.
TAB_COUNT = 4


def navigation(request: HttpRequest) -> dict[str, Any]:
    """Nav items with their active state, the page title and the More tab state."""
    path = request.path

    def leaf(
        label: str, url: str, *, exact: bool = False, badge: str = ""
    ) -> dict[str, Any]:
        active = path == url if exact else path.startswith(url)
        return {"label": label, "url": url, "active": active, "badge": badge}

    def top(
        icon: str, label: str, url: str, *, exact: bool = False, badge: str = ""
    ) -> dict[str, Any]:
        item = leaf(label, url, exact=exact, badge=badge)
        return item | {"icon": icon, "children": []}

    # app_shell.js writes the sidebar sections the user expanded.
    expanded = request.COOKIES.get("nav_expanded", "").split(".")

    def group(icon: str, label: str, children: list[dict[str, Any]]) -> dict[str, Any]:
        key = label.lower()
        active = any(c["active"] for c in children)
        return {
            "icon": icon,
            "key": key,
            "label": label,
            "active": active,
            "open": active or key in expanded,
            "children": children,
        }

    nav = [
        top("home", label="Home", url=reverse("index"), exact=True),
        top("list", label="Transactions", url=reverse("transaction_list")),
        top("inbox", label="Drafts", url=reverse("draft_list"), badge="drafts"),
        top(
            "repeat", label="Schedules", url=reverse("schedule_list"), badge="schedules"
        ),
        top("card", label="Subscriptions", url=reverse("subscription_list")),
        top("trend", label="Forecast", url=reverse("forecast")),
        group(
            "wallet",
            "Accounts",
            [
                leaf(kind.title(), reverse("account_list", args=[kind]))
                for kind in ("asset", "liability", "expense", "income")
            ],
        ),
        group(
            "tag",
            "Classification",
            [leaf("Parties", reverse("party_list")), leaf("Tags", reverse("tag_list"))],
        ),
    ]
    profile = group(
        "user",
        "Profile",
        [
            leaf("Preferences", reverse("preferences")),
            leaf("Change password", reverse("password_change")),
        ],
    )
    title = "Profile" if profile["active"] else "Velora"
    for item in nav:
        if item["active"]:
            title = next(
                (c["label"] for c in item["children"] if c["active"]), item["label"]
            )
    return {
        "nav_tabs": nav[:TAB_COUNT],
        "nav_more": nav[TAB_COUNT:],
        "nav_all": nav,
        "nav_profile": profile,
        "nav_title": title,
        "nav_more_active": profile["active"]
        or any(i["active"] for i in nav[TAB_COUNT:]),
    }
