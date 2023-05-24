import pytest

from utils.pypi import file_path_from_inspector_url

# A collection of random inspector URLs mapped to their respective file paths
test_data = {
    "https://inspector.pypi.io/project/numpy/1.24.3/packages/f3/23/7cc851bae09cf4db90d42a701dfe525780883ada86bece45e3da7a07e76b/numpy-1.24.3-cp310-cp310-macosx_10_9_x86_64.whl/numpy/__init__.pyi": "numpy/__init__.pyi",  # noqa: E501
    "https://inspector.pypi.io/project/numpy/1.24.3/packages/f3/23/7cc851bae09cf4db90d42a701dfe525780883ada86bece45e3da7a07e76b/numpy-1.24.3-cp310-cp310-macosx_10_9_x86_64.whl/numpy/typing/tests/data/fail/twodim_base.pyi": "numpy/typing/tests/data/fail/twodim_base.pyi",  # noqa: E501
    "https://inspector.pypi.io/project/discord-py/2.2.3/packages/36/ce/3ad5a63240b504722dada49d880f9f6250ab861baaba5d27df4f4cb3e34a/discord.py-2.2.3.tar.gz/discord.py-2.2.3/discord/app_commands/checks.py": "discord.py-2.2.3/discord/app_commands/checks.py",  # noqa: E501
    "https://inspector.pypi.io/project/requests/2.19.1/packages/54/1f/782a5734931ddf2e1494e4cd615a51ff98e1879cbe9eecbdfeaf09aa75e9/requests-2.19.1.tar.gz/requests-2.19.1/LICENSE": "requests-2.19.1/LICENSE",  # noqa: E501
}


@pytest.mark.parametrize(
    "inspector_url,file_path", [(inspector_url, file_path) for inspector_url, file_path in test_data.items()]
)
def test_file_path_from_inspector_url(inspector_url: str, file_path: str):
    assert file_path_from_inspector_url(inspector_url) == file_path
