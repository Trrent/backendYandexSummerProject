import datetime

from flask import Blueprint, request, jsonify
from flask_restful import abort
import json

from . import db_session
from .offer import Offer
from .category import Category
from .history import History
from .functions import validate_iso8601, get_date

blueprint = Blueprint(
    'items_api',
    __name__,
    template_folder='templates'
)


@blueprint.errorhandler(400)
def unauthorized(error):
    response = jsonify({
        "code": 400,
        "message": "Validation Failed"
    })
    response.status_code = 400
    return response


@blueprint.errorhandler(400)
def not_found(error):
    response = jsonify({
        "code": 404,
        "message": "Item not found"
    })
    response.status_code = 404
    return response


@blueprint.route('/imports', methods=['POST'])
def imports():
    data = request.json
    if not data:
        abort(400)
    if not data["updateDate"]:
        abort(400)
    if not validate_iso8601(data["updateDate"]):
        abort(400)
    session = db_session.create_session()
    try:
        date = get_date(data["updateDate"])
        for item in request.json["items"]:
            if item["type"] == "CATEGORY":
                it = session.query(Category).filter(Category.category_id == item["id"]).first()
                if not it:
                    it = Category(category_id=item["id"],
                                  name=item["name"],
                                  parent_id=item["parentId"],
                                  date=date)
                    session.add(it)
                else:
                    it.name = item["name"]
                    it.parent_id = item["parentId"]
                    it.date = date
                session.commit()
            elif item["type"] == "OFFER":
                it = session.query(Offer).filter(Offer.offer_id == item["id"]).first()
                if not it:
                    it = Offer(offer_id=item["id"],
                               name=item["name"],
                               price=item["price"],
                               parent_id=item["parentId"],
                               date=date)
                    session.add(it)
                else:
                    it.name = item["name"]
                    it.parent_id = item["parentId"]
                    it.date = date
                add_history_record(item["id"], item["price"], date)
                session.commit()
            else:
                abort(400)
        update_category_price(it.parent_id, date)
        return jsonify({'success': 'OK'})
    except Exception as e:
        abort(400)


@blueprint.route('/nodes/<string:id>', methods=['GET'])
def get_nodes(id):
    try:
        session = db_session.create_session()
        item = session.query(Category).filter(Category.category_id == id).first()
        if not item:
            item = session.query(Offer).filter(Offer.offer_id == id).first()
            if not item:
                abort(404)
            else:
                return jsonify(item.get_info())
        else:
            category_info = item.get_info()
            category_info["childrens"].extend(get_category_info(id))
            return json.dumps(category_info)
    except Exception as e:
        abort(400)


@blueprint.route('/delete/<string:id>', methods=['DELETE'])
def delete_node(id):
    try:
        session = db_session.create_session()
        item = session.query(Category).filter(Category.category_id == id).first()
        if not item:
            item = session.query(Offer).filter(Offer.offer_id == id).first()
            if not item:
                abort(404)
        else:
            delete_children(id)
        parent_id = item.parent_id
        session.delete(item)
        session.commit()
        update_category_price(parent_id, None)
        return jsonify({'success': 'OK'})
    except Exception as e:
        abort(400)


@blueprint.route('/sales', methods=['GET'])
def get_sales():
    try:
        query = request.args["date"]
        if not validate_iso8601(query):
            abort(400)
        response = []
        date = get_date(query)
        last_date = date - datetime.timedelta(hours=24)
        session = db_session.create_session()
        items = session.query(History).filter(History.operation == "update").all()
        for item in items:
            item_date = item.modified_date
            if last_date <= item_date <= date:
                item_info = item.offer.get_info()
                if item_info not in response:
                    response.append(item_info)
        return jsonify({'items': response})
    except Exception as e:
        abort(400)


def add_history_record(offer_id, price, date):
    session = db_session.create_session()
    offer = session.query(Offer).filter(Offer.offer_id == offer_id).first()
    history = History(offer_id=offer_id, price=price, modified_date=date)
    if offer:
        history.operation = 'modified' if offer.price != price else 'update'
    else:
        history.operation = 'modified'
    session.add(history)
    session.commit()


def delete_children(id):
    def delete(parent_id):
        subcategories = session.query(Category).filter(Category.parent_id == parent_id).all()
        for subcategory in subcategories:
            session.delete(subcategory)
            session.commit()
            delete(subcategory.category_id)
        offers = session.query(Offer).filter(Offer.parent_id == parent_id).all()
        for offer in offers:
            session.delete(offer)
            session.commit()
        return

    session = db_session.create_session()
    delete(id)


def get_category_info(id):
    def get_children(id):
        children = []
        subcategories = session.query(Category).filter(Category.parent_id == id).all()
        for subcategory in subcategories:
            subcategory_info = subcategory.get_info()
            subcategory_info["childrens"] = get_children(subcategory.category_id)
            children.append(subcategory_info)
        offers = session.query(Offer).filter(Offer.parent_id == id).all()
        for offer in offers:
            children.append(offer.get_info())
        return children

    session = db_session.create_session()
    children = get_children(id)
    return children


def update_category_price(parent_id, date):
    def update_price(id):
        if id:
            category = session.query(Category).filter(Category.category_id == id).first()
            category_price, category_count = 0, 0
            subcategories = session.query(Category).filter(Category.parent_id == category.category_id).all()
            for subcategory in subcategories:
                category_price, category_count = category_price + subcategory.price, category_count + 1
            offers = session.query(Offer).filter(Offer.parent_id == category.category_id).all()
            for offer in offers:
                category_price, category_count = category_price + offer.price, category_count + 1
            if category_count > 0:
                category.price = category_price // category_count
            else:
                category.price = None
            if date:
                category.date = date
            session.commit()
            update_price(category.parent_id)
        return

    session = db_session.create_session()
    update_price(parent_id)
