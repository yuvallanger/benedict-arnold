import imp
import logging
import os
import sys

"""
This module manages your program's extensions.
Do note that you're still responsible for actually using
them, this only provides an interface to manage them.
"""

logger = logging.getLogger(__name__)

class ExtensionManager(object):
    def __init__(self, search_dirs=(os.path.join(os.path.realpath("."), "extensions"),),
                 blacklist=()):
        """Main extension loader class.
           - search_dirs: Iterable containing where to look for loadable extensions.
                          (The default is ./extensions, where . is the current directory.
           - blacklist: Iterable containing the identifiers of extensions that will
                        not be loaded.
           - init_args: The positional arguments that will be passed to the __init__
                        methods of extensions.
           - init_kwargs: The keyword arguments that will be passed to the __init__
                          methods of extensions."""
        self._recursiondepth = 0
        self.file_map = {}
        self.search_dirs = list(search_dirs)
        self.blacklist = list(blacklist)
        self.extensions = {}

    def count(self):
        """Returns the number of extensions loaded."""
        return len(self.extensions)

    def get_extension(self, ext_id):
        """Try to return the extension object with the identifier ext_id.
           Don't cache references to extension objects. It will cause leaks."""
        try:
            return self.extensions[ext_id]
        except KeyError:
            raise ExtensionMissingError(ext_id)

    def scan_dirs(self):
        """[internal] Refresh the list of extensions that can be loaded."""
        sys.dont_write_bytecode = True
        for path in self.search_dirs:
            logger.info("Scanning directory {0}...".format(os.path.abspath(path)))
            for ext_file in os.listdir(path):
                full_path = os.path.join(path, ext_file)
                if not any((ext_file.endswith(".py"),
                            os.path.isdir(full_path))):
                    continue
                cached_mtime = self.file_map.get(full_path, (0,))[0]
                if os.path.getmtime(full_path) != cached_mtime:
                    mod = imp.load_source("pbx.{0}".format(ext_file), full_path)
                    try:
                        self.check_validity(mod)
                    except LoadError:
                        pass
                    else:
                        self.file_map[full_path] = (os.path.getmtime(full_path),
                                                    mod.__identifier__, mod.__version__)

    def check_validity(self, mod):
        """Check that an extension module has the four magic attributes
           required by the loader."""
        for magic_var in ("__identifier__", "__dependencies__", "__ext_class__",
                          "__version__"):
            if not hasattr(mod, magic_var):
                raise LoadError("The extension in '{0}' has no {1}. It cannot "
                                "be loaded.".format(mod.__file__, magic_var))

    def load_extension_from_file(self, filename, preload_callback):
        """Try to load an extension from filename.
           This will not return an extrnsion object, instead it will return the identifier
           of the extension module.
           Use ExtensionManager.get_extension() to get the loaded extension object."""
        self.scan_dirs()
        for path in self.search_dirs:
            if os.path.join(path, filename) in self.file_map:
                candidate = os.path.join(path, filename)
                break
        else:
            raise LoadError("No such file: {0}".format(filename))
        mod = imp.load_source("pbx.{0}".format(os.path.basename(candidate)), candidate)
        return self.load_with_dependencies(mod, preload_callback)

    def load_with_dependencies(self, mod, preload_callback):
        """Try to load an extension, with all dependencies, from the module mod.
           Returns the identifier of mod on success."""
        self._recursiondepth += 1
        if self._recursiondepth > 15:
            raise DependencyError("We bounced around too many times trying to load {0}."
                                  .format(mod.__file__))
        for dependency in mod.__dependencies__:
            if dependency in self.extensions:
                continue
            for filename in self.file_map:
                if self.file_map[filename][1] == dependency:
                    mod = imp.load_source("pbx.{0}".format(os.path.basename(filename)), filename)
                    self.load_with_dependencies(mod, preload_callback)
            else:
                raise DependencyError("Unsatisfied dependency {0} for extension {1}."
                                      .format(dependency, mod.__file__))
        logger.info("Dependencies loaded.")
        self.extensions[mod.__identifier__] = mod.__ext_class__(*preload_callback(mod))
        self._recursiondepth -= 1
        return mod.__identifier__

    def load_extensions(self, preload_callback):
        """Actually load the extensions.
           preload_callback is called before an extension object is constructed.
           Return values will be passed to the extension's __init__.
           When this method returns, extension objects can be accessed using
           ExtensionManager.get_extension()."""
        sys.dont_write_bytecode = True
        self.scan_dirs()
        modules = []
        for path in self.search_dirs:
            for ext_file in os.listdir(path):
                if not any((ext_file.endswith(".py"),
                            os.path.isdir(os.path.join(path, ext_file)))):
                    continue
                mod = imp.load_source("pbx.{0}".format(ext_file), os.path.join(path, ext_file))
                try:
                    self.check_validity(mod)
                except LoadError as ex:
                    logger.error(str(ex))
                if mod.__identifier__ in self.blacklist:
                    logger.warn("Extension candidate from {0} is on the blacklist. "
                                "Skipping.".format(mod.__file__))
                    continue
                modules.append(mod)
        for ext_module in modules:
            if ext_module.__identifier__ in self.extensions:
                logger.warn("There is already an extension with the identifier '{0}'. "
                            "Skipping.".format(ext_module.__identifier__))
            self.load_with_dependencies(ext_module, preload_callback)
        sys.dont_write_bytecode = False

    def delete_extension(self, ext_id):
        pass

class DependencyError(Exception):
    """Raised on error resolving dependencies."""

class ExtensionMissingError(Exception):
    """Raised when get_extension() fails."""

class LoadError(Exception):
    """Raised when load_extension_from_file fails."""
