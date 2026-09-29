IMAGES := $(shell docker images -f "dangling=true" -q)
CONTAINERS := $(shell docker ps -a -q -f status=exited)
VERSION := 0.1
REPOSITORY := localhost
IMAGE := md-gliner2

ifneq (,$(wildcard .env))
    include .env
    export
endif

clean:
	docker rm -f $(CONTAINERS)
	docker rmi -f $(IMAGES)

build:
	docker build -t $(REPOSITORY)/messydesk/$(IMAGE):$(VERSION) .

start:
	docker run -d --name $(IMAGE) \
		-p 9010:9010 \
		--replace \
		-e MD_URL=http://host.containers.internal:8200 \
		-e DEVICE=cpu \
		--restart unless-stopped \
		$(REPOSITORY)/messydesk/$(IMAGE):$(VERSION)

stop:
	docker stop $(IMAGE)
	docker rm $(IMAGE)

restart:
	docker stop $(IMAGE)
	docker rm $(IMAGE)
	$(MAKE) start

bash:
	docker exec -it $(IMAGE) bash
