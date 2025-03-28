# @mark.steps
# ----------------------------------------------------------------------------
# STEPS:
# ----------------------------------------------------------------------------
import ipaddress
import os
import re
import polling2
import parse
import binascii
import yaml
import json
import time

from behave import given, register_type, then, when, step
from knative_serving import KnativeServing
from namespace import Namespace
from nodejs_application import NodeJSApp
from openshift import Openshift
from quarkus_application import QuarkusApplication
from serverless_operator import ServerlessOperator
from servicebindingoperator import Servicebindingoperator
from app import App
from util import substitute_scenario_id


# STEP
@given(u'Namespace "{namespace_name}" exists')
def namespace_maybe_create(context, namespace_name):
    namespace = Namespace(substitute_scenario_id(context, namespace_name))
    if not namespace.is_present():
        print("Namespace is not present, creating namespace: {}...".format(namespace_name))
        assert namespace.create(), f"Unable to create namespace '{namespace_name}'"
    print("Namespace {} is created!!!".format(namespace_name))
    return namespace


@given(u'Namespace "{namespace_name}" is used')
def namespace_is_used(context, namespace_name):
    context.namespace = namespace_maybe_create(context, namespace_name)


# STEP
@given(u'Namespace [{namespace_env}] is used')
def given_namespace_from_env_is_used(context, namespace_env):
    env = os.getenv(namespace_env)
    assert env is not None, f"{namespace_env} environment variable needs to be set"
    print(f"{namespace_env} = {env}")
    namespace_is_used(context, env)


# STEP
sbo_is_running_in_namespace_step = u'Service Binding Operator is running in "{operator_namespace}" namespace'


@given(sbo_is_running_in_namespace_step)
@when(sbo_is_running_in_namespace_step)
def sbo_is_running_in_namespace(context, operator_namespace):
    """
    Checks if the SBO is up and running in the given namespace
    """
    sb_operator = Servicebindingoperator(namespace=operator_namespace)
    assert sb_operator.is_running(), "Service Binding Operator is not running"
    print("Service binding operator is running!!!")


# STEP
sbo_is_running_in_namespace_from_env_step = u'Service Binding Operator is running in [{operator_namespace_env}] namespace'


@given(sbo_is_running_in_namespace_from_env_step)
@when(sbo_is_running_in_namespace_from_env_step)
def sbo_is_running_in_namespace_from_env(context, operator_namespace_env):
    env = os.getenv(operator_namespace_env)
    assert env is not None, f"{operator_namespace_env} environment variable needs to be set"
    print(f"{operator_namespace_env} = {env}")
    sbo_is_running_in_namespace(context, env)


# STEP
sbo_is_running_step = u'Service Binding Operator is running'


@given(sbo_is_running_step)
@when(sbo_is_running_step)
def sbo_is_running(context):
    if "sbo_namespace" in context:
        sbo_is_running_in_namespace(context, context.sbo_namespace)
    else:
        assert context.namespace is not None, "Namespace is not set in context"
        sbo_is_running_in_namespace(context, context.namespace.name)


# STEP
nodejs_app_imported_from_image_is_running_step = u'Nodejs application "{application_name}" imported from "{application_image}" image is running'


@given(nodejs_app_imported_from_image_is_running_step)
@when(nodejs_app_imported_from_image_is_running_step)
def nodejs_app_imported_from_image_is_running(context, application_name, application_image):
    namespace = context.namespace
    application = NodeJSApp(application_name, namespace.name, application_image)
    if not application.is_running():
        print("application is not running, trying to import it")
        assert application.install(), f"Unable to install application '{application_name}' from image '{application_image}'"
        assert application.is_running(wait=True), f"Unable to start application '{application_name}' from image '{application_image}'"
    print("Nodejs application is running!!!")
    context.application = application
    context.application_type = "nodejs"


# STEP
app_endpoint_is_available_step = u'Application endpoint "{endpoint}" is available'


@given(app_endpoint_is_available_step)
@when(app_endpoint_is_available_step)
@then(app_endpoint_is_available_step)
def app_endpoint_is_available(context, endpoint):
    application = context.application
    assert application.get_response_from_api(endpoint=endpoint) is not None, f'Application endpoint "{endpoint}" is not available'


# STEP
default_nodejs_app_imported_from_image_is_running_step = u'Imported Nodejs application "{application_name}" is running'


@given(default_nodejs_app_imported_from_image_is_running_step)
@when(default_nodejs_app_imported_from_image_is_running_step)
def default_nodejs_app_imported_from_image_is_running(context, application_name):
    nodejs_app_imported_from_image_is_running(context, application_name, application_image="quay.io/pmacik/nodejs-rest-http-crud")
    app_endpoint_is_available(context, endpoint="/api/status/dbNameCM")


# STEP
imported_nodejs_app_is_not_running_step = u'Imported Nodejs application "{application_name}" is not running'


@given(imported_nodejs_app_is_not_running_step)
@when(imported_nodejs_app_is_not_running_step)
def imported_nodejs_app_is_not_running(context, application_name):
    namespace = context.namespace
    application = NodeJSApp(application_name, namespace.name)
    assert application.is_running() is False, "Application is running already"


# STEP
@then(u'application should be re-deployed')
def then_application_redeployed(context):
    application = context.application
    if context.application_type == "nodejs":
        application_pod_name = application.get_redeployed_pod_name(context.application_original_pod_name)
        assert application_pod_name is not None, "There is no running application pod different from the original one before re-deployment."
    elif context.application_type == "knative":
        assert context.application_original_generation is not None, "application is never deployed"
        application_rev_name = application.get_rev_name_redeployed_by_generation(context.application_original_generation)
        assert application_rev_name is not None, "application is not redeployed"
    else:
        assert False, f"Invalid application type in context.application_type={context.application_type}, valid are 'nodejs', 'knative'"


# STEP
@then(u'application should be connected to the DB "{db_name}"')
def then_app_is_connected_to_db(context, db_name):
    db_endpoint = "/api/status/dbNameCM"
    polling2.poll(lambda: context.application.get_response_from_api(endpoint=db_endpoint) == db_name, step=5, timeout=600)


@step(u'Service Binding secret is not present')
def sb_secret_is_not_present(context):
    openshift = Openshift()
    polling2.poll(lambda: openshift.search_resource_in_namespace("secrets", context.sb_secret, context.namespace.name),
                  step=100, timeout=1000, ignore_exceptions=(ValueError,), check_success=lambda v: v is None)


@given(u'Openshift Serverless Operator is running')
def given_serverless_operator_is_running(context):
    """
    Checks if the serverless operator is up and running
    """
    serverless_operator = ServerlessOperator()
    if not serverless_operator.is_running():
        print("Serverless operator is not installed, installing...")
        assert serverless_operator.install_operator_subscription() is True, "serverless operator subscription is not installed"
        assert serverless_operator.is_running(wait=True) is True, "serverless operator not installed"
    context.serverless_operator = serverless_operator


@given(u'Knative serving is running')
def given_knative_serving_is_running(context):
    """
    creates a KnativeServing object to install Knative Serving using the OpenShift Serverless Operator.
    """
    knative_namespace = Namespace("knative-serving")
    if not knative_namespace.is_present():
        assert knative_namespace.create() is True, "Failed to create namespace for Knative Serving"
    knative_serving = KnativeServing(namespace=knative_namespace.name)
    if not knative_serving.is_present():
        print("knative serving is not present, create knative serving")
        assert knative_serving.create() is True, "Failed to create Knative Serving"
        assert knative_serving.is_present() is True, "Knative Serving is not present"


# STEP
quarkus_app_is_imported_step = u'Quarkus application "{application_name}" is imported as Knative service'


@given(quarkus_app_is_imported_step)
@when(quarkus_app_is_imported_step)
def quarkus_app_is_imported_as_knative_service(context, application_name):
    namespace = context.namespace
    application = QuarkusApplication(application_name, namespace.name)
    if not application.is_imported():
        print("application is not imported, trying to import it")
        assert application.install() is True, "Quarkus application is not installed"
        assert application.is_imported(wait=True) is True, "Quarkus application is not imported"
    context.application = application
    context.application_type = "knative"


# STEP
@given(u'CustomResourceDefinition backends.stable.example.com is available')
@given(u'OLM Operator "{backend_service}" is running')
def operator_manifest_installed(context, backend_service=None):
    openshift = Openshift()
    if "namespace" in context:
        ns = context.namespace.name
    else:
        ns = None

    if backend_service is None:
        _ = openshift.apply_yaml_file(os.path.join(os.getcwd(), "test/acceptance/resources/backend_crd.yaml"), namespace=ns)
    else:
        _ = openshift.apply_yaml_file(os.path.join(os.getcwd(), "test/acceptance/resources/", backend_service + ".operator.manifest.yaml"), namespace=ns)


@parse.with_pattern(r'.*')
def parse_nullable_string(text):
    return text


register_type(NullableString=parse_nullable_string)


# STEP
@step(u'Secret contains "{secret_key}" key with value "{secret_value:NullableString}"')
def check_secret_key_value(context, secret_key, secret_value):
    sb = list(context.bindings.values())[0]
    openshift = Openshift()
    secret = polling2.poll(lambda: sb.get_secret_name(), step=100, timeout=1000, ignore_exceptions=(ValueError,), check_success=lambda v: v is not None)
    json_path = f'{{.data.{secret_key}}}'
    polling2.poll(lambda: openshift.get_resource_info_by_jsonpath("secrets", secret, context.namespace.name,
                                                                  json_path) == secret_value,
                  step=5, timeout=120, ignore_exceptions=(binascii.Error,))


# STEP
@then(u'Secret contains "{secret_key}" key with dynamic IP addess as the value')
def check_secret_key_with_ip_value(context, secret_key):
    sb = list(context.bindings.values())[0]
    openshift = Openshift()
    secret = polling2.poll(lambda: sb.get_secret_name(), step=100, timeout=1000, ignore_exceptions=(ValueError,), check_success=lambda v: v is not None)
    json_path = f'{{.data.{secret_key}}}'
    polling2.poll(lambda: ipaddress.ip_address(
        openshift.get_resource_info_by_jsonpath("secrets", secret, context.namespace.name, json_path)),
        step=5, timeout=120, ignore_exceptions=(ValueError,))


# STEP
@given(u'The openshift route is present')
@given(u'Namespace is present')
@given(u'Backend service CSV is installed')
@given(u'The Custom Resource Definition is present')
@given(u'The Custom Resource is present')
@when(u'The Custom Resource is present')
@given(u'The ConfigMap is present')
@given(u'The Secret is present')
@when(u'The Secret is present')
@step(u'The Service is present')
@step(u'The Workload Resource Mapping is present')
def apply_yaml(context, user=None):
    openshift = Openshift()
    resource = substitute_scenario_id(context, context.text)
    metadata = yaml.full_load(resource)["metadata"]
    metadata_name = metadata["name"]
    if "namespace" in metadata:
        ns = metadata["namespace"]
    else:
        if "namespace" in context:
            ns = context.namespace.name
        else:
            ns = None
    output = openshift.apply(resource, ns, user)
    result = re.search(rf'.*{metadata_name}.*(created|unchanged|configured)', output)
    assert result is not None, f"Unable to apply YAML for CR '{metadata_name}': {output}"
    return metadata


# STEP
@given(u'BackingService is deleted')
@when(u'BackingService is deleted')
@step(u'The Workload Resource Mapping is deleted')
def delete_yaml(context):
    openshift = Openshift()
    text = substitute_scenario_id(context, context.text)
    metadata = yaml.full_load(text)["metadata"]
    metadata_name = metadata["name"]
    if "namespace" in metadata:
        ns = metadata["namespace"]
    else:
        if "namespace" in context:
            ns = context.namespace.name
        else:
            ns = None
    output = openshift.delete(text, ns)
    result = re.search(rf'.*{metadata_name}.*(deleted)', output)
    assert result is not None, f"Unable to delete CR '{metadata_name}': {output}"


@step(u'Secret has been injected in to CR "{cr_name}" of kind "{crd_name}" at path "{json_path}"')
def verify_injected_secretRef(context, cr_name, crd_name, json_path):
    sb = list(context.bindings.values())[0]
    name = substitute_scenario_id(context, cr_name)
    openshift = Openshift()
    secret = polling2.poll(lambda: sb.get_secret_name(), step=100, timeout=1000, ignore_exceptions=(ValueError,), check_success=lambda v: v is not None)
    polling2.poll(lambda: openshift.get_resource_info_by_jsonpath(crd_name, name, context.namespace.name, json_path) == secret,
                  step=5, timeout=400)


@then(u'Error message is thrown')
@then(u'Error message "{err_msg}" is thrown')
def validate_error(context, err_msg=None):
    if err_msg is None:
        assert context.expected_error is not None, "An error message should happen"
    else:
        search = re.search(rf'.*{err_msg}.*', context.expected_error)
        assert search is not None, f"Actual error: '{context.expected_error}', Expected error: '{err_msg}'"


@then(u'Service Binding "{sb_name}" is not persistent in the cluster')
def validate_absent_sb(context, sb_name):
    openshift = Openshift()
    polling2.poll(lambda: openshift.search_resource_in_namespace("servicebindings", sb_name, context.namespace.name),
                  step=5, timeout=400, check_success=lambda v: v is None)


@then(u'Secret does not contain "{key}"')
def check_secret_key(context, key):
    sb = list(context.bindings.values())[0]
    openshift = Openshift()
    secret = polling2.poll(lambda: sb.get_secret_name(context), step=100, timeout=1000, ignore_exceptions=(ValueError,), check_success=lambda v: v is not None)
    json_path = f'{{.data.{key}}}'
    polling2.poll(lambda: openshift.get_resource_info_by_jsonpath("secrets", secret, context.namespace.name,
                                                                  json_path) == "",
                  step=5, timeout=120, ignore_exceptions=(binascii.Error,))


def assert_generation(context, count):
    context.latest_application_generation = context.application.get_generation()
    return context.latest_application_generation - context.original_application_generation == int(count)


@then(u'The application got redeployed {count} times so far')
def check_generation(context, count):
    polling2.poll(lambda: assert_generation(context, count), step=5, timeout=400)


@then(u'The application does not get redeployed again with {time} minutes')
def check_no_redeployment(context, time):
    try:
        polling2.poll(lambda: context.application.get_generation() > context.latest_application_generation, step=5, timeout=int(time)*60)
        assert False, "Application has redeployed again unexpectedly"
    except polling2.TimeoutException:
        pass


@given(u'"{app_name}" is deployed from image "{image_ref}"')
def create_deployment(context, app_name, image_ref):
    app = App(app_name, context.namespace.name, image_ref)
    if not app.is_running():
        assert app.install() is True, "Failed to create deployment."


@step(u'User {user} cannot read resource {resource} in namespace {namespace}')
@step(u'User {user} cannot read resource {resource} in test namespace')
def check_resource_unreadable(context, user, resource, namespace=None):
    openshift = Openshift()
    data = resource.split("/")
    res_type = data[0]
    res_name = substitute_scenario_id(context, data[1])
    ns = namespace if namespace is not None else context.namespace.name
    res = openshift.get_resource_info_by_jsonpath(resource_type=res_type, name=res_name, namespace=ns, user=user)
    assert res is None, f"User {user} should not be able to read {resource} in {namespace} namespace"


@step(u'User {user} can read resource {resource}')
def check_resource_readable(context, user, resource, namespace=None):
    openshift = Openshift()
    data = resource.split("/")
    res_type = data[0]
    res_name = substitute_scenario_id(context, data[1])
    ns = namespace if namespace is not None else context.namespace.name
    res = openshift.get_resource_info_by_jsonpath(resource_type=res_type, name=res_name, namespace=ns, user=user)
    assert res is not None, f"User {user} should be able to read {resource} in {ns} namespace"


@step(u'Kind {kind} with apiVersion {group}/{version} is listed in bindable kinds')
def assert_bindable_kind(context, kind, group, version):
    polling2.poll(lambda: exist_bindable_kind(kind, group, version), step=5, timeout=400)


def exist_bindable_kind(kind, group, version):
    openshift = Openshift()
    res = openshift.get_resource_info_by_jsonpath(resource_type="bindablekinds", name="bindable-kinds", json_path="{.status}")
    for gvk in json.loads(res):
        if gvk["group"] == group and gvk["version"] == version and gvk["kind"] == kind:
            return True
    return False


@step(u"User {user} has '{role_name}' role in test namespace")
def user_role_maybe_create(context, user, role_name):
    openshift = Openshift()
    openshift.cli(f"create rolebinding {user}-{role_name} --clusterrole={role_name} --user={user}", context.namespace.name)


@step(u'No user has access to the namespace')
def remove_user_rolebindings(context):
    openshift = Openshift()
    rbs = openshift.get_resource_lst("rolebindings", context.namespace.name)
    for rb in rbs:
        if rb != "service-binding-operator":
            openshift.cli(f"delete rolebinding {rb}", context.namespace.name)


@then(u'cluster role "{cluster_role_name}" is available in the cluster')
def check_cluster_role_exists(context, cluster_role_name):
    openshift = Openshift()
    assert openshift.is_resource_in("clusterroles", cluster_role_name), f"Could not find the cluster role : '{cluster_role_name}' in the cluster"


@then(u'{type}/{resource_name} is available in the cluster')
def check_resource_exists(context, type, resource_name):
    openshift = Openshift()
    assert openshift.is_resource_in(type, resource_name), f"Could not find the resource: '{type}/{resource_name}' in the cluster"


@then(u'operator service account is bound to "{cluster_role_name}" in "{cluster_rolebinding_name}"')
def check_service_account_bound(context, cluster_role_name, cluster_rolebinding_name):
    openshift = Openshift()
    sbr = Servicebindingoperator()
    operator_namespace = openshift.lookup_namespace_for_resource("deployments", sbr.name)
    sa_name = openshift.get_resource_info_by_jsonpath("deployments", sbr.name, operator_namespace, "{.spec.template.spec.serviceAccount}")

    rolebinding_json = openshift.get_json_resource("clusterrolebinding", cluster_rolebinding_name, operator_namespace)
    assert rolebinding_json["roleRef"]["name"] == cluster_role_name, f"Could not find rolebinding for the role '{cluster_role_name}'"

    subjects_list = rolebinding_json["subjects"]
    subject_found = False
    for subject in subjects_list:
        if subject["kind"] == "ServiceAccount" and subject["name"] == sa_name:
            subject_found = True
        else:
            continue

    assert subject_found, f"Could not find rolebinding for the role '{cluster_role_name}'"


@step(u'{time_min} minutes have passed')
def step_impl(context, time_min):
    time.sleep(60 * int(time_min))
