.PHONY: test inventory
test:
	python3 -m unittest discover -s tests -v
inventory:
	python3 -m highdeep inventory
