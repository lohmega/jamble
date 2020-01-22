# Use spaces instead of tabs
.RECIPEPREFIX +=  

.PHONY: clean 

clean:
    rm -fr build/
    rm -fr dist/
    rm -fr .eggs/
    find . -name '*.egg-info' -exec rm -fr {} +
    find . -name '*.egg' -exec rm -f {} +
    
    find . -name '*.pyc' -exec rm -f {} +
    find . -name '*.pyo' -exec rm -f {} +
    find . -name '*~' -exec rm -f {} +
    find . -name '__pycache__' -exec rm -fr {} +

# hack - Using pip ot install is morepermisive then 
# 	python setup.py install
install: clean ## install the 
    python3 setup.py sdist bdist_wheel
    python3 -m pip install dist/lohmega-bblogger-*.tar.gz

#bblog -h
#bblog test -vvvv -a"F2:1F:2B:52:48:9E"
