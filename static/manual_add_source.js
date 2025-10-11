let json_data = {
  "url": "https://shop.costgallery.com/products/midnight-snack-us?variant=46929054990493",
  "title": "Midnight Snack",
  "price": 825,
  "location": "Online",
  "description": "Original author site: It's very serene in the early morning. Those quiet late-night hours are very conducive for getting focused and going with it. Paintings like Midnight Snack are one of the more obvious rewards of such a life style.",
  "condition": "excellent",
  "measurements": "21x15.75",
  "image_url": "https://shop.costgallery.com/cdn/shop/products/midnight_snack_US_4-3_c6cc5613-e0d2-4a07-abf4-77b823665490.png?v=1749782223&width=823"
}
  
fetch(`/listing/15/source/add`, {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    },
    body: JSON.stringify(json_data)
})
.then(response => {
    console.log('Response status:', response.status);
    console.log('Response headers:', response.headers.get('content-type'));
    
    const contentType = response.headers.get('content-type');
    if (!contentType || !contentType.includes('application/json')) {
        throw new Error('Server returned non-JSON response. Check server logs.');
    }
    
    return response.json();
})