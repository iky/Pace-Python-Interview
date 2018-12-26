from datetime import date, datetime, timedelta
from collections import Counter
import itertools
import operator

from flask import Flask, request
from flask_restplus import Api, Resource
from sqlalchemy import and_, func

from models import Bookings, HotelRooms, Hotels
from utils import get_session

app = Flask(__name__)
api = Api(app)

@api.route('/occupancy/<int:hotelroom_id>/<start_date>/<end_date>')
class OccupancyEndpoint(Resource):
    """
    This endpoint returns the current occupancy figure for a hotelroom over a range of nights

    Occupancy Percentage = Total Bookings * 100 / Available Capacity.

    Returns None if available capacity is 0.
    """

    def get(self, hotelroom_id, start_date, end_date):

        # parse the dates as they're sent as a string e.g. 2018-01-01
        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date, '%Y-%m-%d').date()

        # get a session/connection to the database
        session = get_session()

        # get the hotelroom object to calculate capacity
        hotelroom = session.query(HotelRooms).get(hotelroom_id)

        # get number of bookings and cancellations
        num_of_bookings = session.query(func.count(Bookings.id)).filter(
            and_(
                Bookings.hotelroom_id == hotelroom_id,
                Bookings.reserved_night_date.between(
                    start_date, end_date
                ),
                Bookings.row_type == 'booking'
            )
        ).scalar()
        num_of_cancellations = session.query(func.Count(Bookings.id)).filter(
            and_(
                Bookings.hotelroom_id == hotelroom_id,
                Bookings.reserved_night_date.between(
                    start_date, end_date
                ),
                Bookings.row_type == 'cancellations'
            )
        ).scalar()
        num_of_blocked_slots = session.query(func.Count(Bookings.id)).filter(
            and_(
                Bookings.hotelroom_id == hotelroom_id,
                Bookings.reserved_night_date.between(
                    start_date, end_date
                ),
                Bookings.row_type == 'block'
            )
        ).scalar()

        # calculate numerator and denominator for occupancy
        net_bookings = num_of_blocked_slots + num_of_bookings - num_of_cancellations
        total_available_rooms = hotelroom.capacity * ((end_date - start_date).days + 1)

        # check to make sure total_available_rooms is not 0 (division by zero error)
        if total_available_rooms == 0:
            occupancy = None
        else:
            # convert to string and round to 2 decimal places and calculate PERCENTAGE
            occupancy = str(round(net_bookings * 100 / total_available_rooms, 2))

        return {
            'occupancy': occupancy
        }


@api.route('/booking-curve/<int:hotelroom_id>/<reserved_night_date>')
class BookingCurveEndpoint(Resource):
    """
    This endpoint returns a 90 day booking curve for a specific reserved night date.

    occupancy and revenue figures are rounded to the nearest integer.

    e.g.
        {
            "occupancy": [0, 1, 2, 3, 4, 4, 5, 6, 7, 8, 9, 10, 10, 9, 12, 13, 15, ...],
            "revenue: [0, 100, 200, 300, 400, 400, 500, 600, 700, 800, ...]
        }
    """
    def get(self, hotelroom_id, reserved_night_date):

        # get a database session
        session = get_session()

        days = request.args.get("days", 90)
        today = date.today()
        start_date = today - timedelta(days=days-1)

        # bookings made prior the curve start date
        prior_occupancy = session.query(
            func.count(Bookings.id)
        ).filter(
            and_(
                Bookings.hotelroom_id == hotelroom_id,
                Bookings.reserved_night_date == reserved_night_date,
                Bookings.booking_datetime < start_date,
            )
        ).scalar()

        # bookings for the given room and the last 90 days
        bookings = session.query(Bookings.booking_datetime).filter(
            and_(
                Bookings.hotelroom_id == hotelroom_id,
                Bookings.reserved_night_date == reserved_night_date,
                Bookings.booking_datetime >= start_date
            )
        ).all()

        occupancy_per_day = Counter(
            [booking.booking_datetime.date() for booking in bookings]
        )
        # fill up occupancy per each day of the range
        # (including days with no booking)
        occupancy_per_day = [
            occupancy_per_day.get(today - timedelta(days=day), 0)
            for day in reversed(range(days))
        ]
        # add prior occupancy
        occupancy_per_day[0] += prior_occupancy
        # accumulate occupancy curve
        occupancy = list(
            itertools.accumulate(occupancy_per_day, func=operator.add)
        )

        revenue_booking_curve = []

        return {
            'booking_curve': {
                "occupancy": occupancy,
                "revenue": revenue_booking_curve
            }
        }


if __name__ == '__main__':
    app.run(debug=True)
