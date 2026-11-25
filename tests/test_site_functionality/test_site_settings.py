"""Tests for persisted theme settings and template integration."""

import pytest
from cloudinary import CloudinaryResource
from cloudinary import config as cloudinary_config
from colorfield.widgets import ColorWidget
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import Client, RequestFactory

from site_settings.admin import ThemeSettingsAdmin
from site_settings.models import ThemeSettings
from site_settings.templatetags.app_ui import ICON_NAMES, icon

pytestmark = pytest.mark.django_db


def test_site_name_defaults_to_project() -> None:
    """Use the existing project name until a site name is configured."""
    assert ThemeSettings().site_name == "Project"


@pytest.mark.django_db
def test_context_uses_default_branding_without_settings_row(client: Client) -> None:
    """Render safe defaults when the settings singleton has not been created."""
    content = client.get("/").content.decode()

    assert "Project" in content
    assert "All rights reserved." in content
    assert 'uk-icon="icon:' not in content
    assert 'rel="icon"' not in content


def test_font_tokens_render_as_valid_css_declarations(client: Client) -> None:
    """Do not HTML-escape font stacks into invalid CSS values."""
    content = client.get("/").content.decode()

    assert "--theme-font-sans: IBM Plex Sans, system-ui, sans-serif;" in content
    assert "--theme-font-mono: IBM Plex Mono, ui-monospace, monospace;" in content
    assert "--theme-font-sans: &quot;" not in content


def test_rejects_blank_site_name() -> None:
    """Require the configured site name to contain a non-whitespace character."""
    settings = ThemeSettings(site_name="   ")

    with pytest.raises(ValidationError):
        settings.save()


def test_site_name_renders_in_shared_template(
    client: Client, theme_settings: ThemeSettings
) -> None:
    """Render the configured name in the shared branding."""
    theme_settings.site_name = "StreetFix"
    theme_settings.save()

    response = client.get("/")
    content = response.content.decode()

    assert "StreetFix" in content
    assert "© " in content and "StreetFix. All rights reserved." in content


def test_favicon_renders_only_when_configured(
    client: Client,
    theme_settings: ThemeSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Render the Cloudinary URL when set and omit the link when unset."""
    cloudinary_configuration = cloudinary_config()
    monkeypatch.setattr(
        cloudinary_configuration, "cloud_name", "test-cloud", raising=False
    )
    monkeypatch.setattr(cloudinary_configuration, "secure", True, raising=False)
    theme_settings.favicon = CloudinaryResource(
        public_id="branding/favicon",
        format="png",
        resource_type="image",
    )
    theme_settings.save()

    configured_content = client.get("/").content.decode()

    assert (
        '<link href="https://res.cloudinary.com/test-cloud/image/upload/v1/'
        'branding/favicon.png" rel="icon">'
    ) in configured_content

    theme_settings.favicon = None
    theme_settings.save()

    unset_content = client.get("/").content.decode()

    assert 'rel="icon"' not in unset_content


def test_brand_image_renders_beside_wordmark(
    client: Client,
    theme_settings: ThemeSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Render the optional brand image beside the site name."""
    cloudinary_configuration = cloudinary_config()
    monkeypatch.setattr(
        cloudinary_configuration, "cloud_name", "test-cloud", raising=False
    )
    monkeypatch.setattr(cloudinary_configuration, "secure", True, raising=False)
    theme_settings.brand_image = CloudinaryResource(
        public_id="branding/wordmark-mark",
        format="svg",
        resource_type="image",
    )
    theme_settings.save()

    content = client.get("/").content.decode()

    assert "branding/wordmark-mark.svg" in content
    assert 'class="ui-brand__image"' in content
    assert theme_settings.site_name in content


def test_admin_exposes_brand_image_without_navbar_icon() -> None:
    """Expose branding uploads without a fixed navbar icon choice."""
    request = RequestFactory().get("/admin/")
    form_class = ThemeSettingsAdmin(ThemeSettings, AdminSite()).get_form(request)
    form = form_class()

    assert "brand_image" in form.fields
    assert "navbar_brand_icon" not in form.fields
    assert ("site_name", "brand_image", "favicon") in [
        tuple(field for field in fieldset["fields"])
        for _, fieldset in ThemeSettingsAdmin.fieldsets
    ]


def test_theme_admin_change_page_includes_resolved_preview(
    client: Client,
    django_user_model: type[User],
    theme_settings: ThemeSettings,
) -> None:
    """Render the shared resolved variables in the admin preview."""
    admin = django_user_model.objects.create_superuser(
        username="theme-admin",
        email="theme@example.com",
        password="test-password",  # noqa: S106
    )
    client.force_login(admin)

    response = client.get("/site-admin/site_settings/themesettings/1/change/")

    assert response.status_code == 200
    assert b"Theme preview" in response.content
    assert b"--theme-primary:" in response.content


def test_admin_navbar_link_is_removed_without_changing_other_links(
    client: Client, theme_settings: ThemeSettings
) -> None:
    """Keep public navigation while removing only the Admin navbar link."""
    # The home page (report chat) shows only the brand, so check a public page
    # that uses the full navbar.
    content = client.get("/no-such-page/").content.decode()

    assert '<a href="/admin/">Admin</a>' not in content
    assert 'class="ui-nav-link"' in content
    assert 'href="/">Report a problem</a>' in content
    assert 'href="/employees/">Employees</a>' in content
    assert 'href="/analytics/">Analytics</a>' not in content


def test_saves_and_exposes_core_and_optional_theme_values(
    client: Client, theme_settings: ThemeSettings
) -> None:
    """Expose configured theme tokens as safe CSS custom properties."""
    theme_settings.primary_color = "#123456"
    theme_settings.background_color = "#f0f0f0"
    theme_settings.text_color = "#202020"
    theme_settings.radius = "8px"
    theme_settings.surface_color = "#eeeeee"
    theme_settings.link_color = "#654321"
    theme_settings.save()

    response = client.get("/")
    content = response.content.decode()

    assert "--theme-primary: #123456;" in content
    assert "--theme-background: #f0f0f0;" in content
    assert "--theme-text: #202020;" in content
    assert "--theme-radius: 8px;" in content
    assert "--theme-surface: #eeeeee;" in content
    assert "--theme-link: #654321;" in content
    assert "--theme-border:" in content


def test_rejects_invalid_color_values() -> None:
    """Reject values that could break out of a CSS declaration."""
    settings = ThemeSettings(primary_color="red; color: black")

    with pytest.raises(ValidationError):
        settings.save()


@pytest.mark.django_db
def test_rejects_low_contrast_text_before_writing() -> None:
    """Do not persist text/background pairs that fail WCAG AA."""
    settings = ThemeSettings(text_color="#777777")

    with pytest.raises(ValidationError) as error:
        settings.save()

    assert "text_color" in error.value.message_dict
    assert not ThemeSettings.objects.exists()


@pytest.mark.django_db
def test_rejects_low_contrast_derived_primary_links() -> None:
    """Reject a primary color that cannot serve as a link."""
    settings = ThemeSettings(primary_color="#ffffff")

    with pytest.raises(ValidationError) as error:
        settings.save()

    assert "primary_color" in error.value.message_dict
    assert not ThemeSettings.objects.exists()


@pytest.mark.django_db
def test_accepts_text_just_above_the_contrast_threshold() -> None:
    """Accept near-threshold text when explicit tokens keep all pairs legible."""
    settings = ThemeSettings(
        text_color="#767676",
        background_color="#ffffff",
        surface_color="#ffffff",
        emphasis_text_color="#767676",
        muted_text_color="#767676",
    )

    settings.save()

    assert ThemeSettings.objects.get().text_color == "#767676"


@pytest.mark.parametrize(
    ("field_name", "value", "error_field"),
    (
        ("surface_color", "#0f172a", "surface_color"),
        ("link_color", "#777777", "link_color"),
        ("success_surface_color", "#166534", "success_surface_color"),
    ),
)
def test_rejects_low_contrast_explicit_theme_colors(
    field_name: str,
    value: str,
    error_field: str,
) -> None:
    """Attribute contrast errors to explicit surface, link, and status colors."""
    settings = ThemeSettings(**{field_name: value})

    with pytest.raises(ValidationError) as error:
        settings.save()

    assert error_field in error.value.message_dict


@pytest.mark.parametrize(
    ("field_name", "value"),
    (("text_color", "#777777"), ("radius", "2vh")),
)
def test_rejected_theme_update_does_not_change_persisted_value(
    theme_settings: ThemeSettings,
    field_name: str,
    value: str,
) -> None:
    """A failed singleton update leaves the previously stored value intact."""
    previous_value = getattr(theme_settings, field_name)
    setattr(theme_settings, field_name, value)

    with pytest.raises(ValidationError):
        theme_settings.save()

    persisted_settings = ThemeSettings.objects.get(pk=1)
    assert getattr(persisted_settings, field_name) == previous_value


def test_admin_uses_colorfield_picker_for_core_and_optional_colors() -> None:
    """Use django-colorfield pickers, including clearable optional values."""
    request = RequestFactory().get("/admin/")
    form_class = ThemeSettingsAdmin(ThemeSettings, AdminSite()).get_form(request)
    form = form_class()

    assert isinstance(form.fields["primary_color"].widget, ColorWidget)
    assert isinstance(form.fields["surface_color"].widget, ColorWidget)
    assert not form.fields["surface_color"].required


@pytest.mark.parametrize("radius", ("0", "8px", "0.375rem", "1em"))
@pytest.mark.django_db
def test_accepts_valid_radius_values(radius: str) -> None:
    """Accept supported radius values."""
    settings = ThemeSettings(radius=radius)

    settings.save()

    assert ThemeSettings.objects.get().radius == radius


@pytest.mark.parametrize(
    "radius",
    ("1rem; color: red", "8", "-1px", "8vh", ".5rem"),
)
def test_rejects_invalid_radius_values(radius: str) -> None:
    """Reject malformed or unsupported radius values."""
    settings = ThemeSettings(radius=radius)

    with pytest.raises(ValidationError):
        settings.save()


def test_settings_are_a_singleton(theme_settings: ThemeSettings) -> None:
    """Save later settings edits to the existing singleton row."""
    updated_settings = ThemeSettings(primary_color="#654321")
    updated_settings.save()

    assert ThemeSettings.objects.count() == 1
    assert ThemeSettings.objects.get().primary_color == "#654321"


def test_icon_tag_uses_approved_sprite_symbols() -> None:
    """Render approved symbols and reject names outside the fixed set."""
    rendered = str(icon("arrow-right"))

    assert "ui-icon" in rendered
    assert "app-icons" in rendered
    assert "#arrow-right" in rendered
    assert 'aria-hidden="true"' in rendered

    with pytest.raises(ValueError, match="Unknown site icon"):
        icon("not-an-approved-symbol")

    assert "arrow-right" in ICON_NAMES
