"""Tests for semantic styling on django-allauth forms."""

from collections.abc import Iterator
from html.parser import HTMLParser

import pytest
from django import forms
from django.conf import settings as django_settings
from django.template.loader import render_to_string
from django.test import Client, override_settings
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def staticfiles_storage_without_manifest() -> Iterator[None]:
    """Avoid unrelated manifest lookup for the optional favicon route."""
    storages = {
        **django_settings.STORAGES,
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
    with override_settings(STORAGES=storages):
        yield


class FormInputParser(HTMLParser):
    """Collect input attributes for assertions about generated controls."""

    def __init__(self) -> None:
        """Initialize the collected control list."""
        super().__init__()
        self.inputs: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Record attributes for input elements."""
        if tag == "input":
            self.inputs.append(dict(attrs))


def assert_entrance_content_centered(content: str) -> None:
    """Keep account pages inside the shared semantic entrance shell."""
    assert "sf-auth-layout" in content
    assert "sf-auth-card" in content


def test_login_form_uses_semantic_elements(client: Client) -> None:
    """Render login fields with semantic classes and preserve hidden fields."""
    response = client.get(reverse("account_login"), {"next": "/employees/"})
    content = response.content.decode()

    assert response.status_code == 200
    assert 'class="sf-form sf-stack"' in content
    assert 'class="sf-input"' in content
    assert 'for="id_login"' in content
    assert 'id="id_login"' in content
    assert 'name="csrfmiddlewaretoken"' in content
    assert 'name="next" value="/employees/"' in content
    assert "allauth-error-summary-title" not in content
    assert_entrance_content_centered(content)


def test_signup_closed_page_shows_message_and_entrance_layout(client: Client) -> None:
    """Show 'Sign Up Closed' page with entrance layout."""
    response = client.get(reverse("account_signup"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Sign Up Closed" in content
    assert "We are sorry, but the sign up is currently closed." in content
    # No form should be present
    assert 'class="sf-form sf-stack"' not in content
    assert 'name="csrfmiddlewaretoken"' not in content
    assert "sf-auth-card" in content
    assert "<h1>" in content and "Sign Up Closed" in content


def test_password_reset_page_inherits_entrance_alignment(client: Client) -> None:
    """Apply the shared entrance layout to pages beyond login and signup."""
    response = client.get(reverse("account_reset_password"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "sf-auth-card" in content
    assert_entrance_content_centered(content)


def test_account_inactive_page_inherits_entrance_layout(client: Client) -> None:
    """Apply the shared entrance shell to a non-form account page."""
    response = client.get(reverse("account_inactive"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "sf-auth-card" in content


def test_fields_render_semantic_markup_for_choice_and_textarea_widgets() -> None:
    """Render choice controls and textarea values with semantic classes."""

    class WidgetForm(forms.Form):
        choice = forms.ChoiceField(choices=[("a", "Alpha"), ("b", "Beta")])
        notes = forms.CharField(widget=forms.Textarea)
        radios = forms.ChoiceField(
            choices=[("x", "X-ray"), ("y", "Yankee")],
            widget=forms.RadioSelect,
        )
        selected = forms.MultipleChoiceField(
            choices=[("m", "Mike"), ("n", "November")],
            widget=forms.CheckboxSelectMultiple,
        )

    form = WidgetForm(
        {
            "choice": "b",
            "notes": "Preserved note",
            "radios": "y",
            "selected": ["n"],
        }
    )
    content = render_to_string(
        "allauth/elements/fields.html",
        {"attrs": {"form": form}},
    )
    parser = FormInputParser()
    parser.feed(content)

    assert 'class="sf-select"' in content
    assert 'class="sf-textarea"' in content
    assert 'class="sf-radio"' in content
    assert 'class="sf-checkbox"' in content
    assert "selected" in content
    assert "Preserved note" in content
    assert "Radios" in content
    assert all(
        "required" not in control
        for control in parser.inputs
        if control.get("name") == "selected"
    )


def test_signup_post_also_shows_closed_message(client: Client) -> None:
    """POST to signup URL also shows 'Sign Up Closed' when registration is disabled."""
    response = client.post(
        reverse("account_signup"),
        {
            "username": "ada",
            "email": "ada@example.com",
            "password1": "a-long-enough-password",
            "password2": "a-long-enough-password",
        },
    )
    content = response.content.decode()

    assert response.status_code == 200
    assert "Sign Up Closed" in content
    assert "We are sorry, but the sign up is currently closed." in content
    # No form or form errors should be present
    assert 'id="allauth-error-summary-title"' not in content
    assert 'class="uk-form-stacked uk-text-left"' not in content
