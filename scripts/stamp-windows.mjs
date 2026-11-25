import { readFileSync, writeFileSync } from 'node:fs';
import { basename } from 'node:path';
import { Data, NtExecutable, NtExecutableResource, Resource } from 'resedit';

const stagedPath = process.argv[2];
const { productName, version } = JSON.parse(readFileSync(new URL('../package.json', import.meta.url)));
const executableName = `${productName}.exe`;

if (!stagedPath || basename(stagedPath) !== executableName) {
  throw new Error(`Provide the staged Windows executable named ${executableName}.`);
}

const executable = NtExecutable.from(readFileSync(stagedPath));
const resources = NtExecutableResource.from(executable);
const iconFile = Data.IconFile.from(readFileSync(new URL('../electron/relayfold.ico', import.meta.url)));
const frames = iconFile.icons.map(item => item.data);

for (const { id, lang } of Resource.IconGroupEntry.fromEntries(resources.entries)) {
  Resource.IconGroupEntry.replaceIconsForResource(resources.entries, id, lang, frames);
}

for (const resource of Resource.VersionInfo.fromEntries(resources.entries)) {
  for (const translation of resource.getAllLanguagesForStringValues()) {
    resource.setFileVersion(version, translation.lang);
    resource.setProductVersion(version, translation.lang);
    resource.setStringValues(translation, {
      FileDescription: productName,
      InternalName: productName,
      OriginalFilename: executableName,
      ProductName: productName,
    });
  }
  resource.outputToResourceEntries(resources.entries);
}

resources.outputResource(executable);
writeFileSync(stagedPath, new Uint8Array(executable.generate()));
