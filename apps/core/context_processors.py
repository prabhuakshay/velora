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

    def top(  # noqa: PLR0913
        icon: str,
        label: str,
        url: str,
        *,
        exact: bool = False,
        badge: str = "",
        section: str = "",
    ) -> dict[str, Any]:
        # `section` starts a new heading in the sidebar at this item.
        return leaf(label, url, exact=exact, badge=badge) | {
            "icon": icon,
            "section": section,
        }

    nav = [
        top("home", label="Home", url=reverse("index"), exact=True, section="Daily"),
        top("list", label="Transactions", url=reverse("transaction_list")),
        top("inbox", label="Drafts", url=reverse("draft_list"), badge="drafts"),
        top(
            "repeat",
            label="Schedules",
            url=reverse("schedule_list"),
            badge="schedules",
            section="Planning",
        ),
        top("card", label="Subscriptions", url=reverse("subscription_list")),
        top("trend", label="Forecast", url=reverse("forecast")),
        top("target", label="Budgets", url=reverse("budget_list")),
        top(
            "wallet",
            label="Accounts",
            url=reverse("account_list", args=["asset"]),
            section="Wealth",
        )
        # The kind tabs on the page switch kinds, so any kind counts as here.
        | {"active": path.startswith("/accounts/")},
        top("pie", label="Investments", url=reverse("investments_overview")),
        top("flag", label="Goals", url=reverse("goal_list")),
        top("tag", label="Classification", url=reverse("party_list"), section="Setup")
        # The Parties and Tags tabs on the page switch lists, so both count as here.
        | {"active": path.startswith(("/parties/", "/tags/"))},
        top("help", label="Help", url=reverse("help_index")),
    ]
    children = [
        leaf("Preferences", reverse("preferences")) | {"icon": "sliders"},
        leaf("Change password", reverse("password_change")) | {"icon": "key"},
    ]
    profile = {
        "active": any(c["active"] for c in children),
        "children": children,
    }
    title = next(
        (item["label"] for item in nav if item["active"]),
        "Profile" if profile["active"] else "Velora",
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
