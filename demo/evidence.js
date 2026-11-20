export default {
  "recording": {
    "lines": [
      {
        "start": 0.0,
        "speaker": "Shopper",
        "text": "Yaar, ₹50 extra cash on delivery fees kyun lag rahi hai?"
      },
      {
        "start": 4.846,
        "speaker": "Agent",
        "text": "COD orders par fifty rupees charge lagta hai. UPI se pay karne par yeh charge nahi lagega."
      },
      {
        "start": 10.325,
        "speaker": "Shopper",
        "text": "UPI वाला चेकआउट लिंक मेरे WhatsApp पर भेज दो।"
      }
    ],
    "events": [
      {
        "start": 14.607,
        "name": "send_checkout_link",
        "args": {
          "discount_percent": 10,
          "cart_id": "dp-1042",
          "amount": 629
        },
        "ok": true,
        "message": "Mock UPI checkout created.",
        "card": {
          "kind": "checkout",
          "cart_id": "dp-1042",
          "amount": "629.00",
          "savings": "120.00",
          "discount_percent": 10,
          "url": "https://checkout.example/upi/dp-1042"
        }
      }
    ]
  },
  "prices": {
    "cod": "749.00",
    "upi": "629.00",
    "savings": "120.00"
  },
  "fixture": {
    "before": {
      "passed": 4,
      "reply": "I can confirm the total for the items you selected today and then help you finish the checkout whenever you are ready to continue with me."
    },
    "after": {
      "passed": 5,
      "reply": "I can confirm the total and help with your checkout."
    },
    "total": 5
  }
};
