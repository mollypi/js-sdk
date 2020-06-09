from jumpscale.god import j

from jumpscale.sals.chatflows.chatflows import GedisChatBot, chatflow_step, StopChatFlow
from jumpscale.sals.reservation_chatflow.models import SolutionType

from jumpscale.servers.gedis.baseactor import BaseActor, actor_method

from jumpscale.clients.explorer.models import Disk_type, Volume_type
import requests
import math
import time

class FlistDeploy(GedisChatBot):
    steps = [
        "flist_start",
        "flist_network",
        "flist_solution_name",
        "flist_url",
        "container_resources",
        "container_interactive",
        "container_env",
        "container_farm",
        "container_volume",
        "container_volume_details",
        "expiration_time",
        "container_ip",
        "overview",
        "container_pay",
        "container_acess",
    ]

    @chatflow_step()
    def flist_start(self):
        user_info = self.user_info()
        self.user_form_data = dict()
        self.env = dict()
        self.user_form_data["chatflow"] = "flist"
        # j.sal.reservation_chatflow.validate_user(user_info) # TODO bring this back when Auth is ready
        self.md_show("# This wizard will help you deploy a container using any flist provided", md=True)
        
    @chatflow_step(title="Network")
    def flist_network(self):
        self.network = j.sals.reservation_chatflow.select_network(self, j.core.identity.tid)
        self.currency = self.network.currency

    @chatflow_step(title="Solution name")
    def flist_solution_name(self):
        self.user_form_data["Solution name"] = self.string_ask("Please enter a name for your container", required=True, field="name")

    @chatflow_step(title="Flist url")
    def flist_url(self):
        self.user_form_data["Flist link"] = self.string_ask(
            "Please add the link to your flist to be deployed. For example: https://hub.grid.tf/usr/example.flist",
            required=True,
        )

        if "hub.grid.tf" not in self.user_form_data["Flist link"]:
            raise StopChatFlow(
                "This flist is not correct. Please make sure you enter a valid link to an existing flist"
            )

        response = requests.head(self.user_form_data["Flist link"])
        if response.status_code != 200:
            raise StopChatFlow("This flist doesn't exist. Please make sure you enter a valid link to an existing flist")

    @chatflow_step(title="Container resources")
    def container_resources(self):
        form = self.new_form()
        cpu = form.int_ask("Please add how many CPU cores are needed", default=1, required=True)
        memory = form.int_ask("Please add the amount of memory in MB", default=1024, required=True)
        disk = form.single_choice("Select the storage type for your root filesystem", ["SSD", "HDD"], default="SSD")
        self.rootfs_size = form.int_ask("Choose the amount of storage for your root filesystem in MiB", default=256)
        form.ask()
        self.rootfs_type = getattr(Disk_type, disk.value)
        self.user_form_data["CPU"] = cpu.value
        self.user_form_data["Memory"] = memory.value
        self.user_form_data["Root filesystem Type"] = disk.value
        self.user_form_data["Root filesystem Size"] = self.rootfs_size.value

    @chatflow_step(title="Container ineractive & EntryPoint")
    def container_interactive(self):
        self.user_form_data["Interactive"] = self.single_choice(
            "Would you like access to your container through the web browser (coreX)?", ["YES", "NO"], required=True
        )
        if self.user_form_data["Interactive"] == "NO":
            self.user_form_data["Entry point"] = self.string_ask("Please add your entrypoint for your flist") or ""
        else:
            self.user_form_data["Port"] = "7681"
            self.user_form_data["Entry point"] = ""

    @chatflow_step(title="Environment variables")
    def container_env(self):
        self.user_form_data["Env variables"] = self.multi_values_ask("Set Environment Variables")
        self.env.update(self.user_form_data["Env variables"])

    @chatflow_step(title="Container farm")
    def container_farm(self):
        # create new reservation
        self.reservation = j.sals.zos.reservation_create()
        query = {}
        query["mru"] = math.ceil(self.user_form_data["Memory"] / 1024)
        query["cru"] = self.user_form_data["CPU"]

        storage_units = math.ceil(self.rootfs_size.value / 1024)
        if self.user_form_data["Root filesystem Type"] == "SSD":
            query["sru"] = storage_units
        else:
            query["hru"] = storage_units
        farms = j.sals.reservation_chatflow.get_farm_names(1, self, currency=self.currency, **query)
        self.node = j.sals.reservation_chatflow.get_nodes(1, farm_names=farms, currency=self.currency, **query)[0]

    @chatflow_step(title="Attach Volume")
    def container_volume(self):
        volume_attach = self.drop_down_choice(
            "Would you like to attach an extra volume to the container", ["YES", "NO"], required=True, default="NO"
        )
        self.container_volume_attach = volume_attach == "YES" or False

    @chatflow_step(title="Volume details")
    def container_volume_details(self):
        if self.container_volume_attach:
            form = self.new_form()
            vol_disk_type = form.drop_down_choice(
                "Please choose the type of disk for the volume", ["SSD", "HDD"], required=True, default="SSD"
            )
            vol_disk_size = form.int_ask("Please specify the volume size", required=True, default=10)
            vol_mount_point = form.string_ask("Please enter the mount point", required=True, default="/data")
            form.ask()
            self.vol_disk_type = getattr(Volume_type, vol_disk_type.value)
            self.user_form_data["Volume Disk type"] = vol_disk_type.value
            self.user_form_data["Volume Size"] = vol_disk_size.value
            self.user_form_data["Volume mount point"] = vol_mount_point.value

    @chatflow_step(title="Expiration time")
    def expiration_time(self):
        self.expiration = self.datetime_picker(
            "Please enter solution expiration time.",
            required=True,
            min_time=[3600, "Date/time should be at least 1 hour from now"],
            default=j.data.time.get().timestamp + 3900,
        )
        self.user_form_data["Solution expiration"] = j.data.time.get(self.expiration).humanize()
    
    @chatflow_step(title="Container IP & Confirmation about conatiner details")
    def container_ip(self):
        self.network_copy = self.network.copy(j.core.identity.tid)
        self.network_copy.add_node(self.node)
        self.ip_address = self.network_copy.ask_ip_from_node(
            self.node, "Please choose your IP Address for this solution"
        )
        self.user_form_data["IP Address"] = self.ip_address

        self.conatiner_flist = self.user_form_data["Flist link"]
        self.storage_url = "zdb://hub.grid.tf:9900"
        if self.user_form_data["Interactive"] == "YES":
            self.interactive = True
        else:
            self.interactive = False

    @chatflow_step(title="Confirmation")
    def overview(self):
        self.md_show_confirm(self.user_form_data)

    @chatflow_step(title="Container Payment", disable_previous=True)
    def container_pay(self):
        self.network = self.network_copy
        # update network
        self.network.update(j.core.identity.tid, currency=self.currency, bot=self)

        # create container
        cont = j.sals.zos.container.create(
            reservation=self.reservation,
            node_id=self.node.node_id,
            network_name=self.network.name,
            ip_address=self.ip_address,
            flist=self.conatiner_flist,
            storage_url=self.storage_url,
            disk_type=self.rootfs_type.value,
            disk_size=self.rootfs_size.value,
            env=self.env,
            interactive=self.interactive,
            entrypoint=self.user_form_data["Entry point"],
            cpu=self.user_form_data["CPU"],
            memory=self.user_form_data["Memory"],
        )
        if self.container_volume_attach:
            self.volume = j.sals.zos.volume.create(
                self.reservation,
                self.node.node_id,
                size=self.user_form_data["Volume Size"],
                type=self.vol_disk_type.value,
            )
            j.sals.zos.volume.attach(
                container=cont, volume=self.volume, mount_point=self.user_form_data["Volume mount point"]
            )

        metadata = dict()
        metadata["chatflow"] = self.user_form_data["chatflow"]
        metadata["Solution name"] = self.user_form_data["Solution name"]
        metadata["Solution expiration"] = self.user_form_data["Solution expiration"]

        res = j.sals.reservation_chatflow.get_solution_metadata(
            self.user_form_data["Solution name"], SolutionType.Flist, metadata
        )
        reservation = j.sals.reservation_chatflow.add_reservation_metadata(self.reservation, res)
        self.resv_id = j.sals.reservation_chatflow.register_and_pay_reservation(
            reservation, self.expiration, customer_tid=j.core.identity.tid, currency=self.currency, bot=self
        )
        j.sals.reservation_chatflow.save_reservation(
            self.resv_id, self.user_form_data["Solution name"], SolutionType.Flist, self.user_form_data
        )

    @chatflow_step(title="Success", disable_previous=True)
    def container_acess(self):
        if self.interactive:
            res = f"""\
# Container has been deployed successfully: your reservation id is: {self.resv_id}
Open your browser at [http://{self.ip_address}:7681](http://{self.ip_address}:7681)
                """
            self.md_show(res, md=True)
        else:
            res = f"""\
# Container has been deployed successfully: your reservation id is: {self.resv_id}
Your IP is  ```{self.ip_address}```
                """
            self.md_show(res, md=True)


chat = FlistDeploy