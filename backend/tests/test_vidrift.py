import pytest

from integrations.vidrift import build_vidrift_movie_url, build_vidrift_tv_url


def test_vidrift_movie_url():
    assert build_vidrift_movie_url(1440098) == "https://embed.vidrift.net/embed/movie/1440098"


def test_vidrift_tv_url():
    assert build_vidrift_tv_url(1399, 1, 1) == "https://embed.vidrift.net/embed/tv/1399/1/1"


@pytest.mark.parametrize("value", [0, -1, None, "abc"])
def test_invalid_movie_id(value):
    with pytest.raises(ValueError):
        build_vidrift_movie_url(value)


@pytest.mark.parametrize("args", [(0, 1, 1), (1399, 0, 1), (1399, 1, 0), (1399, -1, 1)])
def test_invalid_tv_url(args):
    with pytest.raises(ValueError):
        build_vidrift_tv_url(*args)
