# Copyright 2018 Capital One Services, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from pcf.core import State
from pcf.util import pcf_util
from pcf.core.aws_resource import AWSResource
from botocore.errorfactory import ClientError
from pcf.particle.aws.iam.iam_policy import IAMPolicy

import json

class IAMRole(AWSResource):
    """
    This is the implementation of Amazon's IAM Role.
    """
    flavor = "iam_role"

    state_lookup = {
        "missing": State.terminated,
        "active": State.running,
        "inactive": State.terminated
    }
    equivalent_states = {
        State.running: 1,
        State.stopped: 0,
        State.terminated: 0
    }

    START_PARAMS_FILTER = {
        "RoleName",
        "AssumeRolePolicyDocument",
        "PermissionsBoundary",
        "Path",
        "Tags",
        "Description",
        "MaxSessionDuration"
    }

    UNIQUE_KEYS = ["aws_resource.RoleName"]

    def __init__(self, particle_definition):
        super(IAMRole, self).__init__(
            particle_definition=particle_definition,
            resource_name="iam",
        )
        self.custom_config['policy_arns'] = []
        self.current_state_definition['custom_config'] = {}
        self.role_name = self.desired_state_definition.get('RoleName')
        self._set_unique_keys()

    def _set_unique_keys(self):
        """
        Logic that sets keys from state definition that are used to uniquely identify IAM Policies
        """
        self.unique_keys = IAMRole.UNIQUE_KEYS


    def get_status(self):
        """
        Determines if the IAM Role exists
        Returns:
             status (dict)
        """

        try:
            current_definition = self.client.get_role(RoleName=self.role_name)
        except ClientError as e:
            print(e.response['Error']['Code'])
            if e.response['Error']['Code'] == 'NoSuchEntity':
                return {"status": "missing"}
            else:
                return e
        return current_definition.get('Role')


    def _terminate(self):
        """
        Deletes the IAM Role
        Returns:
             response of boto3 delete_role
        """

        # All role versions must be deleted before default role can be deleted. 

        attached_policies = self.client.list_attached_role_policies(RoleName=self.role_name, PathPrefix=self.desired_state_definition.get('Path', '/'))
        if attached_policies:
            for policy in attached_policies.get('AttachedPolicies'):
                self.client.detach_role_policy(RoleName=self.role_name, PolicyArn=policy.get('PolicyArn'))



        return self.client.delete_role(RoleName=self.role_name)

    def _start(self):
        """
        Creates the IAM Role
        Returns:
             response of boto3 create_role
        """

        create_definition = pcf_util.param_filter(self.get_desired_state_definition(), IAMRole.START_PARAMS_FILTER)
        try:
            self.client.create_role(**create_definition)
        except ClientError as e:
            print(e)

    def _stop(self):
        """
        IAM Role does not have a stopped state so it calls terminate.
        """
        return self.terminate()


    def get_iam_policies(self):
        """
        Check for iam policy parents and returns the iam polcy ids

        Returns:
            iam_policy_id
        """
        desired_policy  = self.custom_config.get('policy_arns', [])
        if len(self.parents) > 0:
            iam_policy_parents = list(filter(lambda x: x.flavor == IAMPolicy.flavor, self.parents))

            if iam_policy_parents:
                for policy_parent in iam_policy_parents:
                    policy_parent.sync_state()
                    if policy_parent.policy_arn not in desired_policy:
                        self.custom_config['policy_arns'].append(policy_parent.policy_arn)


    def sync_state(self):
        """
        Calls get status and then sets the current state.
        """
        full_status = self.get_status()
        if full_status.get("status") == "missing":
            self.state = State.terminated
            return

        self.current_definition = full_status
        self.state = State.running


    def _update(self):
        """
            Updates the IAM Role to match desired state definition. 
        """

        print('need to update')
        desired_policy_arns =  self.custom_config.get('policy_arns', []) 
        print(self.custom_config.get('policy_arns', []) )
        current_policy_arns = self.current_state_definition.get('custom_config', {})

        print(self.current_state_definition.get('custom_config'))
        print(self.custom_config.get('policy_arns'))
        if self.custom_config.get('policy_arns'):
            print('asdf')
            add_policies = list(set(desired_policy_arns) - set(current_policy_arns)) 
            remove_policies = list(set(current_policy_arns) - set(desired_policy_arns))
            if add_policies: 
                for policy_arn in desired_policy_arns:
                    self.client.attach_role_policy(RoleName=self.role_name, PolicyArn=policy_arn)
            if remove_policies:
                for policy_arn in remove_policies:
                    self.client.detach_role_policy(RoleName=self.role_name, PolicyArn=policy_arn)


    def is_state_equivalent(self, state1, state2):
        """
        Determines if states are equivalent. Uses equivalent_states defined in the IAMRole class.
        Args:
            state1 (State):
            state1 (State):
        Returns:
            bool
        """

        return IAMRole.equivalent_states.get(state1) == IAMRole.equivalent_states.get(state2)

    def is_state_definition_equivalent(self):
        """
        Compared the desired state and current state definition

        Returns:
            bool
        """

        self.current_state_definition = pcf_util.param_filter(self.current_definition, IAMRole.START_PARAMS_FILTER)
        self.get_iam_policies()

        #Comparing currently attached policies to desired policies
        attached_policy_arns = self.client.list_attached_role_policies(RoleName=self.role_name, PathPrefix=self.desired_state_definition.get('Path', '/'))

        if attached_policy_arns.get('AttachedPolicies'):
            current_policy_arns = [p.get('PolicyArn') for p in attached_policy_arns.get('AttachedPolicies')]
            self.current_state_definition['custom_config']['policy_arns'] = current_policy_arns

        policy_document = json.loads(self.desired_state_definition.get('AssumeRolePolicyDocument'))

        self.desired_state_definition['custom_config']['policy_arns'].append(self.custom_config.get('policy_arns'))
        self.desired_state_definition['AssumeRolePolicyDocument'] = policy_document
        diff_dict = pcf_util.diff_dict(self.current_state_definition, self.desired_state_definition)
        print(diff_dict)

        return diff_dict == {}



