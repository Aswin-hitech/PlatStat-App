from datetime import datetime
from bson import ObjectId
from repositories import ClassRepository
class_repo = ClassRepository()

class ClassService:
    def __init__(self):
        pass

    def create_class(self, data):
        return class_repo.create_class(data)

    def get_class(self, class_id):
        return class_repo.find_one({"_id": ObjectId(class_id)})

    def list_classes(self, archived=False, search=""):
        return class_repo.list_classes(archived=archived, search=search)

    def update_class(self, class_id, data):
        return class_repo.update_one({"_id": ObjectId(class_id)}, data)

    def archive_class(self, class_id):
        return class_repo.archive_class(class_id)

    def restore_class(self, class_id):
        return class_repo.restore_class(class_id)

    def delete_class(self, class_id):
        return class_repo.delete_class_cascade(class_id)
