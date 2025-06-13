from app.extensions import db

class IngredientPrice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_code = db.Column(db.String(50))
    ingredient_name = db.Column(db.String(100))
    quantity = db.Column(db.Float)
    unit = db.Column(db.String(20))
    unit_price = db.Column(db.Float)
    amount = db.Column(db.Float)
    discount = db.Column(db.Float)
    cgst_tax = db.Column(db.Float)
    sgst_tax = db.Column(db.Float)
    gst_tax = db.Column(db.Float)
    igst_tax = db.Column(db.Float)
    non_gst_tax = db.Column(db.Float)
    total = db.Column(db.Float)
    date = db.Column(db.Date)


    def __repr__(self):
        return f"<IngredientPrice {self.ingredient_name} {self.city} {self.date}>"