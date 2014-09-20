
#
# This script is licensed as public domain.
#

from .utils import PathType, GetFilepath, CheckFilepath, \
                   FloatToString, Vector3ToString, Vector4ToString, \
                   WriteXmlFile

from xml.etree import ElementTree as ET
import bpy
import os
import logging

log = logging.getLogger("ExportLogger")


#-------------------------
# Scene and nodes classes
#-------------------------

# Options for scene and nodes export
class SOptions:
    def __init__(self):
        self.doIndividualPrefab = False
        self.doCollectivePrefab = False
        self.doScenePrefab = False
        self.noPhysics = False
        self.individualPhysics = False
        self.globalPhysics = False
        self.mergeObjects = False


class UrhoSceneMaterial:
    def __init__(self):
        # Material name
        self.name = None
        # List\Tuple of textures
        self.texturesList = None

    def Load(self, uExportData, uGeometry):
        self.name = uGeometry.uMaterialName
        for uMaterial in uExportData.materials:
            if uMaterial.name == self.name:
                self.texturesList = uMaterial.getTextures()
                break


class UrhoSceneModel:
    def __init__(self):
        # Model name
        self.name = None
        # Blender object name
        self.objectName = None
        # Parent Blender object name
        self.parentObjectName = None
        # Model type
        self.type = None
        # List of UrhoSceneMaterial
        self.materialsList = []

    def Load(self, uExportData, uModel, objectName):
        self.name = uModel.name

        self.blenderObjectName = objectName
        if objectName:
            parentObject = bpy.data.objects[objectName].parent
            if parentObject and parentObject.type == 'MESH':
                self.parentObjectName = parentObject.name

        if len(uModel.bones) > 0 or len(uModel.morphs) > 0:
            self.type = "AnimatedModel"
        else:
            self.type = "StaticModel"

        for uGeometry in uModel.geometries:
            uSceneMaterial = UrhoSceneMaterial()
            uSceneMaterial.Load(uExportData, uGeometry)
            self.materialsList.append(uSceneMaterial)


class UrhoScene:
    def __init__(self, blenderScene):
        # Blender scene name
        self.blenderSceneName = blenderScene.name
        # List of UrhoSceneModel
        self.modelsList = []
        # List of all files
        self.files = {}

    # name must be unique in its type
    def AddFile(self, pathType, name, fileUrhoPath):
        if not name:
            log.critical("Name null type:{:s} path:{:s}".format(pathType, fileUrhoPath) )
            return False
        if name in self.files:
            log.critical("Already added type:{:s} name:{:s}".format(pathType, name) )
            return False
        self.files[pathType+name] = fileUrhoPath
        return True

    def FindFile(self, pathType, name):
        if name is None:
            return None
        try:
            return self.files[pathType+name]
        except KeyError:
            return None

    def Load(self, uExportData, objectName):
        for uModel in uExportData.models:
            uSceneModel = UrhoSceneModel()
            uSceneModel.Load(uExportData, uModel, objectName)
            self.modelsList.append(uSceneModel)


#------------------------
# Export materials
#------------------------

def UrhoWriteMaterial(uScene, uMaterial, filepath, fOptions):

    materialElem = ET.Element('material')

    #comment = ET.Comment("Material {:s} created from Blender".format(uMaterial.name))
    #materialElem.append(comment)

    # Technique
    techniquFile = GetFilepath(PathType.TECHNIQUES, uMaterial.techniqueName, fOptions)
    techniqueElem = ET.SubElement(materialElem, "technique")
    techniqueElem.set("name", techniquFile[1])

    # Textures
    if uMaterial.diffuseTexName:
        diffuseElem = ET.SubElement(materialElem, "texture")
        diffuseElem.set("unit", "diffuse")
        diffuseElem.set("name", uScene.FindFile(PathType.TEXTURES, uMaterial.diffuseTexName))

    if uMaterial.normalTexName:
        normalElem = ET.SubElement(materialElem, "texture")
        normalElem.set("unit", "normal")
        normalElem.set("name", uScene.FindFile(PathType.TEXTURES, uMaterial.normalTexName))

    if uMaterial.specularTexName:
        specularElem = ET.SubElement(materialElem, "texture")
        specularElem.set("unit", "specular")
        specularElem.set("name", uScene.FindFile(PathType.TEXTURES, uMaterial.specularTexName))

    if uMaterial.emissiveTexName:
        emissiveElem = ET.SubElement(materialElem, "texture")
        emissiveElem.set("unit", "emissive")
        emissiveElem.set("name", uScene.FindFile(PathType.TEXTURES, uMaterial.emissiveTexName))

    # Parameters
    if uMaterial.diffuseColor:
        diffuseColorElem = ET.SubElement(materialElem, "parameter")
        diffuseColorElem.set("name", "MatDiffColor")
        diffuseColorElem.set("value", Vector4ToString(uMaterial.diffuseColor) )

    if uMaterial.specularColor:
        specularElem = ET.SubElement(materialElem, "parameter")
        specularElem.set("name", "MatSpecColor")
        specularElem.set("value", Vector4ToString(uMaterial.specularColor) )

    if uMaterial.emissiveColor:
        emissiveElem = ET.SubElement(materialElem, "parameter")
        emissiveElem.set("name", "MatEmissiveColor")
        emissiveElem.set("value", Vector3ToString(uMaterial.emissiveColor) )

    if uMaterial.twoSided:
        cullElem = ET.SubElement(materialElem, "cull")
        cullElem.set("value", "none")
        shadowCullElem = ET.SubElement(materialElem, "shadowcull")
        shadowCullElem.set("value", "none")

    WriteXmlFile(materialElem, filepath, fOptions)


def UrhoWriteMaterialsList(uScene, uModel, filepath):

    # Search for the model in the UrhoScene
    for uSceneModel in uScene.modelsList:
        if uSceneModel.name == uModel.name:
            break
    else:
        return

    # Get the model materials and their corresponding file paths
    content = ""
    for uSceneMaterial in uSceneModel.materialsList:
        file = uScene.FindFile(PathType.MATERIALS, uSceneMaterial.name)
        # If the file is missing add a placeholder to preserve the order
        if not file:
            file = "null"
        content += file + "\n"

    try:
        file = open(filepath, "w")
    except Exception as e:
        log.error("Cannot open file {:s} {:s}".format(filepath, e))
        return
    file.write(content)
    file.close()


#------------------------
# Export scene and nodes
#------------------------

# Generate individual prefabs XML
def IndividualPrefabXml(uScene, uSceneModel, sOptions):

    # Set first node ID
    nodeID = 0x1000000

    # Get model file relative path
    modelFile = uScene.FindFile(PathType.MODELS, uSceneModel.name)

    # Gather materials
    materials = ""
    for uSceneMaterial in uSceneModel.materialsList:
        file = uScene.FindFile(PathType.MATERIALS, uSceneMaterial.name)
        if file is None:
            file = ""
        materials += ";" + file

    # Generate xml prefab content
    rootNodeElem = ET.Element('node')
    rootNodeElem.set("id", "{:d}".format(nodeID))

    modelNameElem = ET.SubElement(rootNodeElem, "attribute")
    modelNameElem.set("name", "Name")
    modelNameElem.set("value", uSceneModel.name)

    typeElem = ET.SubElement(rootNodeElem, "component")
    typeElem.set("type", uSceneModel.type)
    typeElem.set("id", "{:d}".format(nodeID))

    modelElem = ET.SubElement(typeElem, "attribute")
    modelElem.set("name", "Model")
    modelElem.set("value", "Model;" + modelFile)

    materialElem = ET.SubElement(typeElem, "attribute")
    materialElem.set("name", "Material")
    materialElem.set("value", "Material" + materials)

    if not sOptions.noPhysics:
        bodyElem = ET.SubElement(rootNodeElem, "component")
        bodyElem.set("type", "RigidBody")
        bodyElem.set("id", "{:d}".format(nodeID+1))

        collisionLayerElem = ET.SubElement(bodyElem, "attribute")
        collisionLayerElem.set("name", "Collision Layer")
        collisionLayerElem.set("value", FloatToString(2))

        gravityElem = ET.SubElement(bodyElem, "attribute")
        gravityElem.set("name", "Use Gravity")
        gravityElem.set("value", "false")

        shapeElem = ET.SubElement(rootNodeElem, "component")
        shapeElem.set("type", "CollisionShape")
        shapeElem.set("id", "{:d}".format(nodeID+2))

        shapeTypeElem = ET.SubElement(shapeElem, "attribute")
        shapeTypeElem.set("name", "Shape Type")
        shapeTypeElem.set("value", "TriangleMesh")

        physicsModelElem = ET.SubElement(shapeElem, "attribute")
        physicsModelElem.set("name", "Model")
        physicsModelElem.set("value", "Model;" + modelFile)

    return rootNodeElem


# Export scene and nodes
def UrhoExportScene(context, uScene, sOptions, fOptions):

    blenderScene = bpy.data.scenes[uScene.blenderSceneName]
    
    '''
    # Re-order meshes
    orderedModelsList = []
    for obj in blenderScene.objects:
        if obj.type == 'MESH':
            for uSceneModel in uScene.modelsList:
                if uSceneModel.objectName == obj.name:
                    orderedModelsList.append(uSceneModel)
    uScene.modelsList = orderedModelsList
    '''

    k = 0x1000000   # node ID
    compoID = k     # component ID

    # Create scene components
    if sOptions.doScenePrefab:
        sceneRoot = ET.Element('scene')
        sceneRoot.set("id", "1")

        octreeElem = ET.SubElement(sceneRoot, "component")
        octreeElem.set("type", "Octree")
        octreeElem.set("id", "1")

        debugElem = ET.SubElement(sceneRoot, "component")
        debugElem.set("type", "DebugRenderer")
        debugElem.set("id", "2")

        lightElem = ET.SubElement(sceneRoot, "component")
        lightElem.set("type", "Light")
        lightElem.set("id", "3")

        lightTypeElem = ET.SubElement(lightElem, "attribute")
        lightTypeElem.set("name", "Light Type")
        lightTypeElem.set("value", "Directional")

        if not sOptions.noPhysics:
            physicsElem = ET.SubElement(sceneRoot, "component")
            physicsElem.set("type", "PhysicsWorld")
            physicsElem.set("id", "4")

        # Create Root node
        root = ET.SubElement(sceneRoot, "node")
    else: 
        # Root node
        root = ET.Element('node') 

    root.set("id", "{:d}".format(k))
    sceneElem = ET.SubElement(root, "attribute")
    sceneElem.set("name", "Name")
    sceneElem.set("value", uScene.blenderSceneName)

    # Create physics stuff for the root node
    if sOptions.globalPhysics:
        rigidBodyElem = ET.SubElement(root, "component")
        rigidBodyElem.set("type", "RigidBody")
        rigidBodyElem.set("id", "{:d}".format(compoID))

        layerElem = ET.SubElement(rigidBodyElem, "attribute")
        layerElem.set("name", "Collision Layer")
        layerElem.set("value", "2")

        gravityElem = ET.SubElement(rigidBodyElem, "attribute")
        gravityElem.set("name", "Use Gravity")
        gravityElem.set("value", "false")

        shapeElem = ET.SubElement(root, "component")
        shapeElem.set("type", "CollisionShape")
        shapeElem.set("id", "{:d}".format(compoID+1))

        shapeTypeElem = ET.SubElement(shapeElem, "attribute")
        shapeTypeElem.set("name", "Shape Type")
        shapeTypeElem.set("value", "TriangleMesh")

        physicsModelFile = GetFilepath(PathType.MODELS, "Physics", fOptions)[1]
        modelElem = ET.SubElement(shapeElem, "attribute")
        modelElem.set("name", "Model")
        modelElem.set("value", "Model;" + physicsModelFile)
        compoID += 2

    # Export each decomposed object
    for uSceneModel in uScene.modelsList:

        # Get model file relative path
        modelFile = uScene.FindFile(PathType.MODELS, uSceneModel.name)

        # Gather materials
        materials = ""
        for uSceneMaterial in uSceneModel.materialsList:
            file = uScene.FindFile(PathType.MATERIALS, uSceneMaterial.name)
            if file is None:
                file = ""
            materials += ";" + file

        # Generate XML Content
        k += 1
        modelNode = uSceneModel.name

        # If child node, parent to parent object instead of root
        nodeElem = ET.SubElement(root, "node")
        if uSceneModel.type == "StaticModel" and uSceneModel.parentObjectName:
            for usm in uScene.modelsList:
                if usm.name == uSceneModel.parentObjectName:
                    nodeElem = ET.SubElement(a[usm.name], "node") 
                    break;

        nodeElem.set("id", "{:d}".format(k))

        nodeNameElem = ET.SubElement(nodeElem, "attribute")
        nodeNameElem.set("name", "Name")
        nodeNameElem.set("value", uSceneModel.name)

        nodeTypeElem = ET.SubElement(nodeElem, "component")
        nodeTypeElem.set("type", uSceneModel.type)
        nodeTypeElem.set("id", "{:d}".format(compoID))

        nodeModelElem = ET.SubElement(nodeTypeElem, "attribute")
        nodeModelElem.set("name", "Model")
        nodeModelElem.set("value", "Model;" + modelFile)

        nodeMaterialElem = ET.SubElement(nodeTypeElem, "attribute")
        nodeMaterialElem.set("name", "Material")
        nodeMaterialElem.set("value", "Material" + materials)
        compoID += 1

        if sOptions.individualPhysics:
            rigidBodyElem = ET.SubElement(nodeElem, "component")
            rigidBodyElem.set("type", "RigidBody")
            rigidBodyElem.set("id", "{:d}".format(compoID))

            layerElem = ET.SubElement(rigidBodyElem, "attribute")
            layerElem.set("name", "Collision Layer")
            layerElem.set("value", "{:f}".format(2))

            gravityElem = ET.SubElement(rigidBodyElem, "attribute")
            gravityElem.set("name", "Use Gravity")
            gravityElem.set("value", "false")

            shapeElem = ET.SubElement(nodeElem, "component")
            shapeElem.set("type", "CollisionShape")
            shapeElem.set("id", "{:d}".format(compoID+1))

            shapeTypeElem = ET.SubElement(shapeElem, "attribute")
            shapeTypeElem.set("name", "Shape Type")
            shapeTypeElem.set("value", "TriangleMesh")

            modelElem = ET.SubElement(shapeElem, "attribute")
            modelElem.set("name", "Model")
            modelElem.set("value", "Model;" + modelFile)

            compoID += 2

        # Write individual prefabs
        if sOptions.doIndividualPrefab:
            xml = IndividualPrefabXml(uScene, uSceneModel, sOptions)
            filepath = GetFilepath(PathType.OBJECTS, uSceneModel.name, fOptions)
            if CheckFilepath(filepath[0], fOptions):
                log.info( "Creating prefab {:s}".format(filepath[1]) )
                WriteXmlFile(xml, filepath[0], fOptions)

        # Merging objects equates to an individual export. And collective equates to individual, so we can skip collective
        if sOptions.mergeObjects and sOptions.doScenePrefab: 
            filepath = GetFilepath(PathType.SCENES, uScene.blenderSceneName, fOptions)
            if CheckFilepath(filepath[0], fOptions):
                log.info( "Creating scene prefab {:s}".format(filepath[1]) )
                WriteXmlFile(sceneRoot, filepath[0], fOptions)

    # Write collective and scene prefab files
    if not sOptions.mergeObjects:

        if sOptions.doCollectivePrefab:
            filepath = GetFilepath(PathType.OBJECTS, uScene.blenderSceneName, fOptions)
            if CheckFilepath(filepath[0], fOptions):
                log.info( "Creating collective prefab {:s}".format(filepath[1]) )
                WriteXmlFile(root, filepath[0], fOptions)

        if sOptions.doScenePrefab:
            filepath = GetFilepath(PathType.SCENES, uScene.blenderSceneName, fOptions)
            if CheckFilepath(filepath[0], fOptions):
                log.info( "Creating scene prefab {:s}".format(filepath[1]) )
                WriteXmlFile(sceneRoot, filepath[0], fOptions)
