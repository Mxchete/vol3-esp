# CNT6519 Final Project

This repository details the setup of the experiment for our CNT6519 final project.
The operating system used for this experiment was ```NixOS 26.11 (Zokor) x86_64```. Other Linux-based x86_64 operating systems with access to nix and direnv should work, however. The user should also be part of the ```dialout``` group, in order to access the ESP32.

Due to the nature of the setup for this project, the only 2 dependencies needed beforehand are nix and direnv. These 2 dependencies will automatically install the required software needed upon entering the directory.
The versions of nix and direnv used are:

- nix 2.34.9
- direnv 2.38.2

The hardware required to run this experiment is:

- An x86_64 desktop running Linux (preferrably the version mentioned above)
- an ESP32 DEVKITV1 + USB capable of connecting the ESP to the computer

After installing direnv, hook it into you bash shell by running the following commands to add the hook to your bashrc:
```
echo 'eval "$(direnv hook bash)"' >> ~/.bashrc
source ~/.bashrc
```
You can then enter the root directory. Most Likely, you will need to run
```
direnv allow .
```
and then exit and re-enter the directory to install the software.

Upon entering the root directory, wait for the software to install. Then initialize the esp32 software using:
```
idf.py set-target esp32
```
Then, run the following command to find your ESP32.
```
/dev/tty*
```
Typically, your ESP32 will appear under /dev as ttyUSB*. The project automatically assumes the ESP is ttyUSB0, so if the device is different, this will need to be updated.
Set the ESP environment variable to update this value using
```
export ESP=/path/to/your/esp
```
Once the ESP is set, run the commands provided by run-commands.sh
```
./run-commands.sh
```

TODO:
Explain getting image from GDB, and intermediary steps
