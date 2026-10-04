CONTAINER_RUNTIME ?= podman
VERSION := 0.2
REPOSITORY := localhost
IMAGE := md-gliner2
LOCAL_IMAGE := $(REPOSITORY)/messydesk/$(IMAGE):$(VERSION)

ifneq (,$(wildcard .env))
    include .env
    export
endif

# The model is downloaded into the image at build time (a few minutes the first time).
build:
	$(CONTAINER_RUNTIME) build -t $(LOCAL_IMAGE) .

start:
	$(CONTAINER_RUNTIME) run -d --name $(IMAGE) \
		-p 9010:9010 \
		--replace \
		-e DEVICE=cpu \
		--restart unless-stopped \
		$(LOCAL_IMAGE)

stop:
	-$(CONTAINER_RUNTIME) stop $(IMAGE)
	-$(CONTAINER_RUNTIME) rm $(IMAGE)

restart: stop start

bash:
	$(CONTAINER_RUNTIME) exec -it $(IMAGE) bash

# The tests run in the image with the baked-in model (HF_HUB_OFFLINE: it is never downloaded).
test: build
	$(CONTAINER_RUNTIME) run --rm -e HOME=/tmp -e PYTHONUSERBASE=/tmp/pyuser \
		-v $(CURDIR)/tests:/app/tests:ro,Z $(LOCAL_IMAGE) \
		sh -c "pip install -q --user pytest && python -m pytest -q -p no:cacheprovider tests"
