# TODO: Create a new droplet
# TODO: Create a new ssh key for the droplet - find way of storing securely
# TODO: Provision the droplet

droplet_ip="167.71.94.59"
ssh -i keys/droplet.pub root@${droplet_ip} 