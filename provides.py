"""
This is the provides side of the interface layer, for use only by the AWS
integrator charm itself.

The flags that are set by the provides side of this interface are:

* **`endpoint.{endpoint_name}.requested`** This flag is set when there is
  a new or updated request by a remote unit for AWS integration features.
  The AWS integration charm should then iterate over each request, perform
  whatever actions are necessary to satisfy those requests, and then mark
  them as complete.
"""

import json
from hashlib import sha256

from charmhelpers.core import hookenv, unitdata

from charms.reactive import Endpoint
from charms.reactive import when
from charms.reactive import toggle_flag, clear_flag


class AWSIntegrationProvides(Endpoint):
    """
    Example usage:

    ```python
    from charms.reactive import when, endpoint_from_flag
    from charms import layer

    @when('endpoint.aws.requested')
    def handle_requests():
        aws = endpoint_from_flag('endpoint.aws.requested')
        for request in aws.requests:
            if request.instance_tags:
                tag_instance(
                    request.instance_id,
                    request.region,
                    request.instance_tags)
            if request.requested_load_balancer_management:
                layer.aws.enable_load_balancer_management(
                    request.application_name,
                    request.instance_id,
                    request.region,
                )
            # ...
            request.mark_completed()
    ```
    """

    @when('endpoint.{endpoint_name}.changed')
    def check_requests(self):
        unfulfilled_requests = False
        for request in self.all_requests:
            if request.changed:
                hookenv.log(f'Marking request for processing for {request.unit_name} from {request.instance_id}')
                unfulfilled_requests = True
            elif not request.is_completed and request.completed_for_instance:
                request.mark_completed()
                hookenv.log(f'Marking request as completed for {request.unit_name} from {request.instance_id}')
        toggle_flag(self.expand_name('requested'), unfulfilled_requests)
        clear_flag(self.expand_name('changed'))

    @when('endpoint.{endpoint_name}.departed')
    def cleanup(self):
        for unit in self.all_departed_units:
            request = IntegrationRequest(unit)
            request.clear()
        self.all_departed_units.clear()
        clear_flag(self.expand_name('departed'))

    @property
    def requests(self):
        """
        A list of the new or updated #IntegrationRequests that
        have been made.
        """
        return [request for request in self.all_requests if request.changed]

    @property
    def all_requests(self):
        """
        A list of all the #IntegrationRequests that have been made,
        even if unchanged.
        """
        return [IntegrationRequest(unit) for unit in self.all_joined_units]

    @property
    def application_names(self):
        """
        Set of names of all applications that are still joined.
        """
        return {unit.application_name for unit in self.all_joined_units}

    @property
    def unit_instances(self):
        """
        Mapping of unit names to instance IDs and regions for all joined units.
        """
        return {
            unit.unit_name: {
                'instance-id': unit.received['instance-id'],
                'region': unit.received['region'],
            } for unit in self.all_joined_units
        }


class IntegrationRequest:
    """
    A request for integration from a single remote unit.
    """
    def __init__(self, unit):
        self._unit = unit
        self._hash = sha256(json.dumps(dict(unit.received),
                                       sort_keys=True).encode('utf8')
                            ).hexdigest()

    @property
    def hash(self):
        """
        SHA hash of the data for this request.
        """
        return self._hash

    @property
    def _hash_key(self):
        endpoint = self._unit.relation.endpoint
        return endpoint.expand_name('request.{}'.format(self.instance_id))

    @property
    def changed(self):
        """
        Whether this request has changed since the last time it was
        marked completed.
        """
        if not (self.instance_id and self._requested):
            return False
        saved_hash = unitdata.kv().get(self._hash_key)
        return saved_hash != self.hash

    def mark_completed(self):
        """
        Mark this request as having been completed.
        """
        completed = self._unit.relation.to_publish.get('completed', {})
        completed[self.instance_id] = self.hash
        unitdata.kv().set(self._hash_key, self.hash)
        self._unit.relation.to_publish['completed'] = completed

    def clear(self):
        """
        Clear this request's cached data.
        """
        unitdata.kv().unset(self._hash_key)

    @property
    def unit_name(self):
        """
        The name of the unit making the request.
        """
        return self._unit.unit_name

    @property
    def application_name(self):
        """
        The name of the application making the request.
        """
        return self._unit.application_name

    @property
    def completed_for_instance(self):
        instance_hash = unitdata.kv().get(self._hash_key)
        return self.instance_id and self._requested and instance_hash and instance_hash == self.hash

    @property
    def is_completed(self):
        completed = self._unit.relation.to_publish.get('completed', {})
        return completed.get(self.instance_id) == self.hash

    @property
    def _requested(self):
        return self._unit.received['requested']

    @property
    def instance_id(self):
        """
        The instance ID reported for this request.
        """
        return self._unit.received['instance-id']

    @property
    def region(self):
        """
        The region reported for this request.
        """
        return self._unit.received['region']

    @property
    def instance_tags(self):
        """
        Mapping of tag names to values (or `None`) to apply to this instance.
        """
        # uses dict() here to make a copy, just to be safe
        return dict(self._unit.received.get('instance-tags', {}))

    @property
    def instance_security_group_tags(self):
        """
        Mapping of tag names to values (or `None`) to apply to this instance's
        machine-specific security group (firewall).
        """
        # uses dict() here to make a copy, just to be safe
        return dict(self._unit.received.get('instance-security-group-tags',
                                            {}))

    @property
    def instance_subnet_tags(self):
        """
        Mapping of tag names to values (or `None`) to apply to this instance's
        subnet.
        """
        # uses dict() here to make a copy, just to be safe
        return dict(self._unit.received.get('instance-subnet-tags', {}))

    @property
    def requested_instance_inspection(self):
        """
        Flag indicating whether the ability to inspect instances was requested.
        """
        return bool(self._unit.received['enable-instance-inspection'])

    @property
    def requested_acm_readonly(self):
        """
        Flag indicating whether acm readonly was requested.
        """
        return bool(self._unit.received['enable-acm-readonly'])

    @property
    def requested_acm_fullaccess(self):
        """
        Flag indicating whether acm fullaccess was requested.
        """
        return bool(self._unit.received['enable-acm-fullaccess'])

    @property
    def requested_network_management(self):
        """
        Flag indicating whether the ability to manage networking (firewalls,
        subnets, etc) was requested.
        """
        return bool(self._unit.received['enable-network-management'])

    @property
    def requested_load_balancer_management(self):
        """
        Flag indicating whether load balancer management was requested.
        """
        return bool(self._unit.received['enable-load-balancer-management'])

    @property
    def requested_block_storage_management(self):
        """
        Flag indicating whether block storage management was requested.
        """
        return bool(self._unit.received['enable-block-storage-management'])

    @property
    def requested_dns_management(self):
        """
        Flag indicating whether DNS management was requested.
        """
        return bool(self._unit.received['enable-dns-management'])

    @property
    def requested_object_storage_access(self):
        """
        Flag indicating whether object storage access was requested.
        """
        return bool(self._unit.received['enable-object-storage-access'])

    @property
    def object_storage_access_patterns(self):
        """
        List of patterns to which to restrict object storage access.
        """
        return list(
            self._unit.received['object-storage-access-patterns'] or [])

    @property
    def requested_object_storage_management(self):
        """
        Flag indicating whether object storage management was requested.
        """
        return bool(self._unit.received['enable-object-storage-management'])

    @property
    def object_storage_management_patterns(self):
        """
        List of patterns to which to restrict object storage management.
        """
        return list(
            self._unit.received['object-storage-management-patterns'] or [])

    @property
    def requested_ses_readonly(self):
        """
        Flag indicating whether ses readonly was requested.
        """
        return bool(self._unit.received['enable-ses-readonly'])

    @property
    def requested_ses_fullaccess(self):
        """
        Flag indicating whether ses fullaccess was requested.
        """
        return bool(self._unit.received['enable-ses-fullaccess'])

    @property
    def requested_sns_readonly(self):
        """
        Flag indicating whether sns readonly was requested.
        """
        return bool(self._unit.received['enable-sns-readonly'])

    @property
    def requested_sns_fullaccess(self):
        """
        Flag indicating whether sns fullaccess was requested.
        """
        return bool(self._unit.received['enable-sns-fullaccess'])

    @property
    def requested_mobiletargeting_readonly(self):
        """
        Flag indicating whether pinpoint mobiletargeting readonly was requested.
        """
        return bool(self._unit.received['enable-mobiletargeting-readonly'])

    @property
    def requested_mobiletargeting_fullaccess(self):
        """
        Flag indicating whether pinpoint mobiletargeting fullaccess was requested.
        """
        return bool(self._unit.received['enable-mobiletargeting-fullaccess'])

    @property
    def requested_sms_voice_readonly(self):
        """
        Flag indicating whether pinpoint sms voice readonly was requested.
        """
        return bool(self._unit.received['enable-sms-voice-readonly'])

    @property
    def requested_sms_voice_fullaccess(self):
        """
        Flag indicating whether pinpoint sms voice fullaccess was requested.
        """
        return bool(self._unit.received['enable-sms-voice-fullaccess'])
