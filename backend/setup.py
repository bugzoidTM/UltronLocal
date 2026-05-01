from setuptools import setup, find_packages

setup(
    name="ultronpro",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "fastapi>=0.111.0",
        "uvicorn>=0.30.1",
    ],
)
