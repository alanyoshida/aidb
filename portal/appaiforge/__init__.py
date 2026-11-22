"""Portal AIDB. A versão vem do pacote instalado (o `version` do pyproject.toml, change
version-alignment): é a mesma do chart, das imagens padrão dos sistemas e da release."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("appaiforge-portal")
except PackageNotFoundError:  # código importado sem instalar o pacote: não inventa uma versão
    __version__ = "0+desconhecida"
