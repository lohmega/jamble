import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()
    

REQUIRED = [
    "protobuf",
    # Linux 
    'bleak > 0.5.0;platform_system=="Linux"',
    # MacOS 
    'bleak > 0.5.1;platform_system=="Darwin"',
    # Windows 
    'bleak > 0.5.0;platform_system=="Windows"',
]


setuptools.setup(
    name="lohmega-bblogger", # TODO username
    version="0.1",
    author="",
    author_email="author@example.com",
    entry_points={"console_scripts": ["bblog=bblogger.cli:main"]},   
    description="Cli tool and lib for Lohmega BlueBerry logger",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/lohmega/jamble",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.4',
)
