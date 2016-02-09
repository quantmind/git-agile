# Ansible roles

This library ships several ansible roles for deployment of python applications.
To use these roles, add the ``git-agile/ansible/roles`` path to the ``roles_path``
in the ``ansible.cfg`` file.
```
[defaults]
roles_path  = ../../git-agile/ansible/roles
```
## Pyserver Role

Install packages needed to build python using [pyenv](https://github.com/yyuu/pyenv).
Some of the code was taken from [ansible-galaxy-pyenv](https://github.com/avanov/ansible-galaxy-pyenv)
and subsequently modified.

## Grant github user Role

Grant a developer the admin rights on a machine by installing the developer
public keys from github.

## Nginx Role

Install and configure nginx. The key variable is the list of ``nginx_domains``
to install in the server. This list contains objects of the form
```yml
{
    name: "mydomain.com",
    certificate: "certificate/location",
    websocket: true,
    host: "local.domain",
    port: "5050"
}
```

## Redis Role

Install and configure redis (ubuntu 15+ only)