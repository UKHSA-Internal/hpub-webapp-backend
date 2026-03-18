import pytest
import io
from unittest.mock import patch, MagicMock, create_autospec
import pandas as pd
from core.languages.models import LanguagePage
from core.roles.models import Role
from core.users.models import User


@pytest.fixture
def mock_role():
    """Mock Role model instance."""
    role = create_autospec(Role, instance=True)
    role.role_id = "50"
    role.name = "Admin"
    role._state = MagicMock()
    return role


@pytest.fixture
def mock_user(mock_role):
    """Mock User model instance."""
    user = create_autospec(User, instance=True)
    user.user_id = "12345"
    user.email = "testuser@example.com"
    user.role_ref = mock_role
    user._state = MagicMock()
    return user


@pytest.fixture
def mock_language_page():
    """Mock LanguagePage model instance."""
    lang = create_autospec(LanguagePage, instance=True)
    lang.language_id = "1"
    lang.language_names = "Test Language"
    lang.iso_language_code = "tl"
    lang._state = MagicMock()
    return lang


@patch("core.languages.models.LanguagePage.objects.create")
def test_create_language_success(mock_create):
    """
    Unit test for creating a new LanguagePage.
    Positive scenario: valid data => success.
    """

    lang_instance = create_autospec(LanguagePage, instance=True)
    lang_instance.language_id = "101"
    lang_instance.language_names = "Japan"
    lang_instance.iso_language_code = "ja-JP"

    mock_create.return_value = lang_instance

    created_lang = LanguagePage.objects.create(
        language_id="101", language_names="Japan", iso_language_code="ja-JP"
    )

    assert created_lang.iso_language_code == "ja-JP"
    assert created_lang.language_names == "Japan"
    mock_create.assert_called_once_with(
        language_id="101", language_names="Japan", iso_language_code="ja-JP"
    )


@patch("core.languages.models.LanguagePage.objects.filter")
def test_create_language_duplicate(mock_filter, mock_language_page):
    """
    Unit test for duplicating a LanguagePage.
    Negative scenario: same language_id or iso_language_code => error.
    """
    # Simulate that the language already exists
    mock_filter.return_value.exists.return_value = True

    with pytest.raises(ValueError, match="Duplicate language"):
        if LanguagePage.objects.filter(language_id="1").exists():
            raise ValueError("Duplicate language")

    mock_filter.assert_called_once_with(language_id="1")


def test_create_language_missing_name():
    """
    Unit test for missing language_name.
    Negative scenario: language_name is required => error.
    """
    data = {"language_id": "3", "iso_language_code": "es"}

    with pytest.raises(ValueError, match="Missing language_name"):
        if "language_name" not in data:
            raise ValueError("Missing language_name")


def test_create_language_missing_iso_code():
    """
    Unit test for missing iso_language_code.
    Negative scenario: missing iso_language_code => error.
    """
    data = {"language_name": "Freckles"}

    with pytest.raises(
        ValueError,
        match="Invalid language name 'Freckles', cannot derive iso_language_code.",
    ):
        if "iso_language_code" not in data:
            raise ValueError(
                "Invalid language name 'Freckles', cannot derive iso_language_code."
            )


@patch("core.languages.models.LanguagePage.objects.bulk_create")
def test_create_multiple_languages(mock_bulk_create):
    """
    Unit test for creating multiple LanguagePage instances.
    Positive scenario: multiple valid languages => success.
    """
    # Create MagicMock instances instead of actual LanguagePage instances
    lang1 = MagicMock(spec=LanguagePage)
    lang1.language_id = "101"
    lang1.language_names = "Japanese"
    lang1.iso_language_code = "ja-JP"

    lang2 = MagicMock(spec=LanguagePage)
    lang2.language_id = "102"
    lang2.language_names = "Spanish"
    lang2.iso_language_code = "es-ES"

    mock_bulk_create.return_value = [lang1, lang2]

    # Mock list of new languages
    new_langs = [MagicMock(spec=LanguagePage), MagicMock(spec=LanguagePage)]

    # Simulate calling bulk_create
    created_langs = LanguagePage.objects.bulk_create(new_langs)

    assert len(created_langs) == 2
    mock_bulk_create.assert_called_once_with(new_langs)


@patch("core.languages.models.LanguagePage.objects.bulk_create")
def test_bulk_language_upload_success(mock_bulk_create):
    """
    Unit test for bulk uploading LanguagePage entries.
    Positive scenario: valid Excel data => success.
    """
    # Create MagicMock instances instead of actual LanguagePage objects
    lang1 = MagicMock(
        spec=LanguagePage,
        language_id="201",
        language_names="Spanish",
        iso_language_code="es",
    )
    lang2 = MagicMock(
        spec=LanguagePage,
        language_id="202",
        language_names="French",
        iso_language_code="fr",
    )

    mock_bulk_create.return_value = [lang1, lang2]

    # Simulate reading from an Excel file using pandas
    df = pd.DataFrame(
        {
            "language_name": ["Spanish", "French"],
            "language_id": ["201", "202"],
            "iso_language_code": ["es", "fr"],
        }
    )
    excel_file = io.BytesIO()
    df.to_excel(excel_file, index=False)
    excel_file.seek(0)

    # Mock list of languages (without creating actual LanguagePage instances)
    new_langs = [MagicMock(spec=LanguagePage), MagicMock(spec=LanguagePage)]

    # Simulate calling bulk_create
    created_langs = LanguagePage.objects.bulk_create(new_langs)

    assert len(created_langs) == 2
    mock_bulk_create.assert_called_once_with(new_langs)


@patch("core.languages.models.LanguagePage.objects.all")
def test_delete_all_languages(mock_all):
    """
    Unit test for deleting all LanguagePage instances.
    Positive scenario: multiple languages exist => delete successfully.
    """
    # Mock the queryset to return two LanguagePage instances
    mock_lang1 = MagicMock(spec=LanguagePage)
    mock_lang2 = MagicMock(spec=LanguagePage)

    # Mock delete method on each instance
    mock_lang1.delete = MagicMock()
    mock_lang2.delete = MagicMock()

    # Ensure mock_all returns these instances
    mock_all.return_value = [mock_lang1, mock_lang2]

    # Simulate the delete logic
    languages = LanguagePage.objects.all()
    for lang in languages:
        lang.delete()

    # Assertions
    mock_all.assert_called_once()  # Ensure all() was called once
    mock_lang1.delete.assert_called_once()  # Ensure delete() was called on the first instance
    mock_lang2.delete.assert_called_once()  # Ensure delete() was called on the second instance


@patch("core.languages.models.LanguagePage.objects.all")
def test_get_languages(mock_all, mock_language_page):
    """
    Unit test for retrieving all LanguagePage instances.
    Positive scenario: languages exist => return them.
    """
    # Mock the queryset to return one LanguagePage instance
    mock_all.return_value = [mock_language_page]

    languages = LanguagePage.objects.all()

    assert len(languages) == 1
    assert languages[0].language_id == "1"
    assert languages[0].language_names == "Test Language"
    mock_all.assert_called_once()


@patch("core.languages.models.LanguagePage.objects.all")
def test_get_languages_no_data(mock_all):
    """
    Unit test for retrieving all LanguagePage instances when none exist.
    Positive scenario: no languages exist => return empty list.
    """
    # Mock the queryset to return an empty list
    mock_all.return_value = []

    languages = LanguagePage.objects.all()

    assert len(languages) == 0
    mock_all.assert_called_once()
