job "md-gliner2" {
  type = "service"

  group "MD-Gliner2" {
    count = 1

    restart {
      attempts = 2
      interval = "5m"
      delay    = "15s"
      mode     = "fail"
    }

    reschedule {
      attempts       = 2
      interval       = "10m"
      delay          = "30s"
      delay_function = "constant"
      unlimited      = false
    }

    network {
      port "node" {
        to = 9010
      }
    }

    service {
      name     = "md-gliner2"
      port     = "node"
      provider = "nomad"
      
      check {
        type     = "http"
        path     = "/health"
        interval = "10s"
        timeout  = "3s"
      }
    }

    task "md-gliner2" {
      driver = "podman"
      config {
          image = "localhost/messydesk/md-gliner2:0.2"
          force_pull = false
          ports = ["node"]
          # Disk mode: the service reads and writes MessyDesk's data directory. Adjust the host paths.
          volumes = [
            "/srv/messydesk:/md",
          ]
      }
      env {
        PORT = "9010"
        MD_PATH = "/md"
        # "cuda" on a GPU host (needs a CUDA build of torch in the image)
        DEVICE = "cpu"
      }
      resources {
        memory = 4000  # Memory in MB (the model takes about 2 GB)
        cpu    = 500  # CPU shares (500 = 50% of 1 CPU)
      }
    }
  }
}