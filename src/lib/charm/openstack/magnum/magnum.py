from __future__ import absolute_import

import base64
import collections
import os

import charms.leadership as leadership
import charms_openstack.charm
import charms_openstack.adapters as adapters
import charms_openstack.ip as os_ip
import charmhelpers.core.host as ch_host
import charmhelpers.core.hookenv as ch_hookenv
import charmhelpers.fetch as fetch


PACKAGES = [
    'magnum-api',
    'magnum-conductor',
    'python3-mysqldb',
    'python3-magnumclient']

MAGNUM_DIR = '/etc/magnum/'
MAGNUM_CONF = os.path.join(MAGNUM_DIR, 'magnum.conf')
MAGNUM_PASTE_API = os.path.join(MAGNUM_DIR, 'api-paste.ini')
KEYSTONE_POLICY = os.path.join(MAGNUM_DIR, 'keystone_auth_default_policy.json')
POLICY = os.path.join(MAGNUM_DIR, 'policy.json')
CA_CERT_FILE = os.path.join(MAGNUM_DIR, 'cluster-nodes-ca.crt')
VALID_NOTIFICATION_DRIVERS = [
    'messaging', 'messagingv2', 'routing', 'log', 'test', 'noop']

MAGNUM_SERVICES = [
    'magnum-api',
    'magnum-conductor']


# select the default release function
charms_openstack.charm.use_defaults('charm.default-select-release')

def _allowed_drivers():
    allowed_drivers = ch_hookenv.config().get(
        'allowed-network-drivers')
    if allowed_drivers:
        asArray = allowed_drivers.split()
        return asArray
    return []


@adapters.config_property
def k8s_allowed_network_drivers(arg):
    allowed_drivers = _allowed_drivers()
    if len(allowed_drivers) > 0:
        return ",".join(allowed_drivers)


@adapters.config_property
def k8s_default_network_driver(arg):
    default_driver = ch_hookenv.config().get(
        'default-network-driver')
    allowed_drivers = _allowed_drivers()
    if default_driver in allowed_drivers:
        return default_driver


@adapters.config_property
def magnum_password(arg):
    passwd = leadership.leader_get("magnum_password")
    if passwd:
        return passwd


def default_ca_file_path():
    pth = os.path.join(
        ch_host.CA_CERT_DIR, "{}.crt".format(ch_hookenv.service_name()))
    if os.path.exists(pth):
        return pth
    return None


def _additional_ca():
    ca = ch_hookenv.config().get('additional-ca-certs')
    if ca:
        decoded = base64.b64decode(ca)
        return decoded
    return None


@adapters.config_property
def ca_file_path(arg):
    default_ca = default_ca_file_path()
    additional_ca = _additional_ca()

    if default_ca is None and additional_ca is None:
        return ""

    default_ca_contents = None
    if default_ca:
        with open(default_ca, 'rb') as f:
            default_ca_contents = f.read()

    with open(CA_CERT_FILE, 'wb') as f:
        if default_ca_contents:
            f.write(default_ca_contents)
        if additional_ca:
            f.write(additional_ca)

    return CA_CERT_FILE


@adapters.config_property
def oslo_notification_driver(arg):
    driver = ch_hookenv.config().get(
        'notification-driver')
    if driver in VALID_NOTIFICATION_DRIVERS:
        return driver
    return ''


def db_sync_done():
    return MagnumCharm.singleton.db_sync_done()


def restart_all():
    MagnumCharm.singleton.restart_all()


def db_sync():
    MagnumCharm.singleton.db_sync()


def configure_ha_resources(hacluster):
    MagnumCharm.singleton.configure_ha_resources(hacluster)


def assess_status():
    MagnumCharm.singleton.assess_status()


def setup_endpoint(keystone):
    charm = MagnumCharm.singleton
    public_ep = '{}/v1'.format(charm.public_url)
    internal_ep = '{}/v1'.format(charm.internal_url)
    admin_ep = '{}/v1'.format(charm.admin_url)
    keystone.register_endpoints(charm.service_type,
                                charm.region,
                                public_ep,
                                internal_ep,
                                admin_ep)


class MagnumCharm(charms_openstack.charm.HAOpenStackCharm):

    abstract_class = False
    release = 'ussuri'
    name = 'magnum'
    packages = PACKAGES
    python_version = 3
    api_ports = {
        'magnum-api': {
            os_ip.PUBLIC: 9511,
            os_ip.ADMIN: 9511,
            os_ip.INTERNAL: 9511,
        }
    }
    service_type = 'magnum'
    default_service = 'magnum-api'
    services = MAGNUM_SERVICES
    sync_cmd = ['magnum-db-manage', 'upgrade']

    required_relations = [
        'shared-db', 'amqp', 'identity-service']

    restart_map = {
        MAGNUM_CONF: services,
        MAGNUM_PASTE_API: [default_service, ],
        KEYSTONE_POLICY: services,
        POLICY: services,
    }

    ha_resources = ['vips', 'haproxy']

    # Package for release version detection
    release_pkg = 'magnum-common'

    # Package codename map for magnum-common
    package_codenames = {
        'magnum-common': collections.OrderedDict([
            ('10', 'ussuri'),
            ('11', 'victoria'),
        ]),
    }

    group = "magnum"

    # TODO: Remove this 'install' hook wrapper once the Magnum packages are
    # fixed in the cloud archive / default repositories.
    # We use a 3rd party PPA with custom Magnum packages (built against
    # Magnum stable branch) because they include a couple of needed fixes.
    # Due to the amount of changes needed to fix Magnum Ussuri, we went with
    # the separate PPA to have the charm working.
    # A good indication that Magnum is fixed in the cloud archive / default
    # repositories, is removing this 'install' wrapper, and having the Zaza
    # tests still passing.
    def install(self):
        custom_ppa_dict = {
            'ussuri': 'ppa:openstack-charmers/magnum-ussuri',
            'victoria': 'ppa:openstack-charmers/magnum-victoria',
        }
        ppa = custom_ppa_dict.get(self.application_version)
        if ppa:
            fetch.add_source(ppa, fail_invalid=True)
            fetch.apt_update(fatal=True)
        super().install()

    def get_amqp_credentials(self):
        """Provide the default amqp username and vhost as a tuple.
        :returns (username, host): two strings to send to the amqp provider.
        """
        return (self.config['rabbit-user'], self.config['rabbit-vhost'])

    def get_database_setup(self):
        return [
            dict(
                database=self.config['database'],
                username=self.config['database-user'], )
        ]

    @property
    def local_address(self):
        """Return local address as provided by our ConfigurationClass."""
        return self.configuration_class().local_address

    @property
    def local_unit_name(self):
        """Return local unit name as provided by our ConfigurationClass."""
        return self.configuration_class().local_unit_name

    def _validate_notification_driver(self):
        driver = self.config.get('notification-driver')
        if driver not in VALID_NOTIFICATION_DRIVERS:
            raise ValueError(
                'Notification driver %s is not valid. Valid '
                'notifications drivers are: %s' % (
                    driver, ", ".join(VALID_NOTIFICATION_DRIVERS))
            )

    def custom_assess_status_check(self):
        try:
            self._validate_notification_driver()
        except Exception as err:
            msg = ('Invalid notification driver: %s' % err)
            return 'blocked', msg

        return (None, None)
