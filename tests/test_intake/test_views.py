"""Tests for intake application views."""

import pytest
from django.test import Client
from django.urls import resolve, reverse

from intake.views import ReportChatView

pytestmark = pytest.mark.django_db


def test_home_page_url_exists_at_desired_location(client: Client) -> None:
    """Test that the home page is accessible at the root URL."""
    response = client.get("/")

    assert response.status_code == 200


def test_home_page_url_accessible_by_name(client: Client) -> None:
    """Test that the home page is accessible by its URL name."""
    response = client.get(reverse("intake:form_intake"))

    assert response.status_code == 200


def test_home_page_uses_report_chat_template(client: Client) -> None:
    """Test that the home page is the report chat."""
    response = client.get(reverse("intake:form_intake"))

    assert any(
        template.name == "intake/report_chat.html" for template in response.templates
    )


def test_home_page_extends_base_template(client: Client) -> None:
    """Test that the home page template extends base.html."""
    response = client.get(reverse("intake:form_intake"))

    assert any(template.name == "base.html" for template in response.templates)


def test_base_template_loads_component_styles(client: Client) -> None:
    """Load fonts, tokens, layout, and components without UIkit."""
    response = client.get(reverse("intake:form_intake"))
    content = response.content.decode()

    assert "uikit/uikit.min" not in content
    assert "css/fonts" in content
    assert "css/layout" in content
    assert "css/components" in content


def test_home_page_resolves_to_report_chat_view() -> None:
    """Test that the root URL resolves to the ReportChatView class."""
    resolver_match = resolve("/")

    assert getattr(resolver_match.func, "view_class", None) is ReportChatView


def test_home_page_context_contains_expected_content(client: Client) -> None:
    """Test that the response contains the chat heading."""
    response = client.get(reverse("intake:form_intake"))
    content = response.content.decode()

    assert "Report a problem" in content
